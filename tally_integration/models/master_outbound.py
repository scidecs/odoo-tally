# -*- coding: utf-8 -*-
"""Outbound hooks for non-financial Tally masters."""
import logging
from decimal import Decimal

from odoo import api, models

_logger = logging.getLogger(__name__)


def _instances(record, entity, company=None):
    company = company or record.env.company
    instances = record.env["tally.instance"].search([
        ("company_id", "=", company.id),
        ("active", "=", True),
    ])
    return instances.filtered(lambda instance: any(
        config.entity == entity and config.enabled
        and config.direction in ("odoo_to_tally", "both")
        for config in instance.entity_config_ids))


def _enqueue(record, entity, builder, company=None):
    """Build and queue one master for each eligible company instance."""
    for instance in _instances(record, entity, company=company):
        guid = record.env["tally.mapping"].outbound_guid(
            instance, entity, record._name, record.id)
        message = builder(instance, guid)
        from ..services import tally_xml_builder
        payload = tally_xml_builder.wrap_import_envelope(
            [message], company_name=instance.tally_company)
        if not record.env["tally.mapping"].register_outbound(
                instance, entity, record._name, record.id, payload,
                guid=guid, allow_tally_origin=True):
            continue
        record.env["tally.sync.queue"].create({
            "instance_id": instance.id,
            "entity": entity,
            "odoo_model_name": record._name,
            "odoo_res_id": record.id,
            "idempotency_key": "%s:%s" % (entity, guid),
            "payload": payload,
            "state": "pending",
        })


class UomUom(models.Model):
    _inherit = "uom.uom"

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if not self.env.context.get("tally_no_sync"):
            records._enqueue_tally_uom()
        return records

    def write(self, vals):
        result = super().write(vals)
        if not self.env.context.get("tally_no_sync"):
            self._enqueue_tally_uom()
        return result

    def _enqueue_tally_uom(self):
        from ..services import tally_xml_builder
        for record in self:
            try:
                dec = 0
                if record.rounding and record.rounding < 1:
                    s = f"{record.rounding:.6f}".rstrip("0")
                    if "." in s:
                        dec = len(s.split(".")[1])
                _enqueue(record, "uom", lambda _i, guid: tally_xml_builder.build_unit_xml(
                    record.name, formal_name=record.name, decimal_places=dec, guid=guid))
            except Exception as exc:
                _logger.warning("Tally UoM enqueue skipped for %s: %s", record.id, exc)


class ProductCategory(models.Model):
    _inherit = "product.category"

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if not self.env.context.get("tally_no_sync"):
            records._enqueue_tally_stock_group()
        return records

    def write(self, vals):
        result = super().write(vals)
        if not self.env.context.get("tally_no_sync"):
            self._enqueue_tally_stock_group()
        return result

    def _enqueue_tally_stock_group(self):
        from ..services import tally_xml_builder
        for record in self:
            try:
                _enqueue(record, "stock_group", lambda _i, guid: tally_xml_builder.build_stock_group_xml(
                    record.name, parent=record.parent_id.name if record.parent_id else None,
                    guid=guid))
            except Exception as exc:
                _logger.warning("Tally stock-group enqueue skipped for %s: %s", record.id, exc)


class StockLocation(models.Model):
    _inherit = "stock.location"

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if not self.env.context.get("tally_no_sync"):
            records._enqueue_tally_godown()
        return records

    def write(self, vals):
        result = super().write(vals)
        if not self.env.context.get("tally_no_sync"):
            self._enqueue_tally_godown()
        return result

    def _enqueue_tally_godown(self):
        from ..services import tally_xml_builder
        for record in self.filtered(lambda r: r.usage == "internal"):
            try:
                company = record.company_id or self.env.company
                _enqueue(record, "godown", lambda _i, guid: tally_xml_builder.build_godown_xml(
                    record.name, parent=None, guid=guid), company=company)
            except Exception as exc:
                _logger.warning("Tally godown enqueue skipped for %s: %s", record.id, exc)


class AccountAnalyticAccount(models.Model):
    _inherit = "account.analytic.account"

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if not self.env.context.get("tally_no_sync"):
            records._enqueue_tally_cost_centre()
        return records

    def write(self, vals):
        result = super().write(vals)
        if not self.env.context.get("tally_no_sync"):
            self._enqueue_tally_cost_centre()
        return result

    def _enqueue_tally_cost_centre(self):
        from ..services import tally_xml_builder
        for record in self:
            try:
                company = record.company_id or self.env.company
                _enqueue(record, "cost_centre", lambda _i, guid: tally_xml_builder.build_cost_centre_xml(
                    record.name, guid=guid), company=company)
            except Exception as exc:
                _logger.warning("Tally cost-centre enqueue skipped for %s: %s", record.id, exc)


class AccountTax(models.Model):
    _inherit = "account.tax"

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if not self.env.context.get("tally_no_sync"):
            records._enqueue_tally_tax()
        return records

    def write(self, vals):
        result = super().write(vals)
        if not self.env.context.get("tally_no_sync"):
            self._enqueue_tally_tax()
        return result

    def _enqueue_tally_tax(self):
        from ..services import tally_xml_builder
        for record in self.filtered(lambda r: r.amount_type == "percent"):
            try:
                lower = (record.name or "").lower()
                gst_type = "IGST" if "igst" in lower else ("SGST" if "sgst" in lower else "CGST")
                _enqueue(record, "tax", lambda _i, guid: tally_xml_builder.build_tax_ledger_xml(
                    record.name, gst_type=gst_type, rate=record.amount, guid=guid),
                    company=record.company_id)
            except Exception as exc:
                _logger.warning("Tally tax enqueue skipped for %s: %s", record.id, exc)
