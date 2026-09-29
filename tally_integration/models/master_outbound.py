# -*- coding: utf-8 -*-
"""Outbound hooks for non-financial Tally masters."""
import html
import logging
import re

from odoo import api, models

from .compat import uom_decimal_places

_logger = logging.getLogger(__name__)


def _enqueue(record, entity, builder, company=None):
    """Build and queue one master for every instance that should receive it.

    ``builder(instance, guid, old_name)`` returns the TALLYMESSAGE; ``old_name``
    is the name Tally currently holds when the record is already linked, so a
    rename alters the existing Tally master instead of creating another one.
    """
    from ..services import tally_xml_builder
    from .tally_outbound import enqueue, target_instances
    for instance in target_instances(record.env, entity, company):
        Mapping = record.env["tally.mapping"].sudo()
        guid = Mapping.outbound_guid(instance, entity, record._name, record.id)
        old_name = Mapping.outbound_address(instance, entity, record._name, record.id).get("name")
        message = builder(instance, guid, old_name)
        payload = tally_xml_builder.wrap_import_envelope(
            [message], company_name=instance.tally_company)
        # The name Tally will hold after this push (the <NAME> element).
        new_name = re.search(r"<NAME>(.*?)</NAME>", message)
        enqueue(instance, entity, record, payload, guid,
                tally_name_value=html.unescape(new_name.group(1)) if new_name else record.name,
                allow_tally_origin=True)


class UomUom(models.Model):
    _inherit = "uom.uom"
    TALLY_FIELDS = {"name", "rounding", "relative_factor"}

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if not self.env.context.get("tally_no_sync"):
            records._enqueue_tally_uom()
        return records

    def write(self, vals):
        result = super().write(vals)
        if not self.env.context.get("tally_no_sync") and self.TALLY_FIELDS.intersection(vals):
            self._enqueue_tally_uom()
        return result

    def _enqueue_tally_uom(self):
        from ..services import tally_xml_builder
        for record in self:
            try:
                dec = uom_decimal_places(record)
                # Same name stock items and vouchers reference (Units -> Nos).
                unit = tally_xml_builder.normalize_tally_uom(record.name)
                _enqueue(record, "uom", lambda _i, guid, _old: tally_xml_builder.build_unit_xml(
                    unit, formal_name=record.name, decimal_places=dec, guid=guid))
            except Exception as exc:
                _logger.warning("Tally UoM enqueue skipped for %s: %s", record.id, exc)


class ProductCategory(models.Model):
    _inherit = "product.category"
    TALLY_FIELDS = {"name", "parent_id"}

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if not self.env.context.get("tally_no_sync"):
            records._enqueue_tally_stock_group()
        return records

    def write(self, vals):
        result = super().write(vals)
        if not self.env.context.get("tally_no_sync") and self.TALLY_FIELDS.intersection(vals):
            self._enqueue_tally_stock_group()
        return result

    def _enqueue_tally_stock_group(self):
        from ..services import tally_xml_builder
        for record in self:
            try:
                _enqueue(record, "stock_group", lambda _i, guid, old: tally_xml_builder.build_stock_group_xml(
                    record.name, parent=record.parent_id.name if record.parent_id else None,
                    guid=guid, old_name=old))
            except Exception as exc:
                _logger.warning("Tally stock-group enqueue skipped for %s: %s", record.id, exc)


class StockLocation(models.Model):
    _inherit = "stock.location"
    TALLY_FIELDS = {"name", "location_id", "usage"}

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if not self.env.context.get("tally_no_sync"):
            records._enqueue_tally_godown()
        return records

    def write(self, vals):
        result = super().write(vals)
        if not self.env.context.get("tally_no_sync") and self.TALLY_FIELDS.intersection(vals):
            self._enqueue_tally_godown()
        return result

    def _enqueue_tally_godown(self):
        from ..services import tally_xml_builder
        mains = self.env["stock.warehouse"].sudo().search([]).mapped("lot_stock_id")
        for record in self.filtered(lambda r: r.usage == "internal" and r not in mains):
            try:
                from .tally_outbound import godown_name
                _enqueue(record, "godown", lambda inst, guid, old: tally_xml_builder.build_godown_xml(
                    godown_name(inst, record), parent=None, guid=guid, old_name=old),
                    company=record.company_id)
            except Exception as exc:
                _logger.warning("Tally godown enqueue skipped for %s: %s", record.id, exc)


class AccountAnalyticAccount(models.Model):
    _inherit = "account.analytic.account"
    TALLY_FIELDS = {"name", "plan_id"}

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if not self.env.context.get("tally_no_sync"):
            records._enqueue_tally_cost_centre()
        return records

    def write(self, vals):
        result = super().write(vals)
        if not self.env.context.get("tally_no_sync") and self.TALLY_FIELDS.intersection(vals):
            self._enqueue_tally_cost_centre()
        return result

    def _enqueue_tally_cost_centre(self):
        from ..services import tally_xml_builder
        for record in self:
            try:
                _enqueue(record, "cost_centre", lambda _i, guid, old: tally_xml_builder.build_cost_centre_xml(
                    record.name, guid=guid, old_name=old), company=record.company_id)
            except Exception as exc:
                _logger.warning("Tally cost-centre enqueue skipped for %s: %s", record.id, exc)


class AccountTax(models.Model):
    _inherit = "account.tax"
    TALLY_FIELDS = {"name", "amount", "amount_type", "type_tax_use"}

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if not self.env.context.get("tally_no_sync"):
            records._enqueue_tally_tax()
        return records

    def write(self, vals):
        result = super().write(vals)
        if not self.env.context.get("tally_no_sync") and self.TALLY_FIELDS.intersection(vals):
            self._enqueue_tally_tax()
        return result

    def _enqueue_tally_tax(self):
        from ..services import tally_xml_builder
        for record in self.filtered(lambda r: r.amount_type == "percent"):
            try:
                lower = (record.name or "").lower()
                gst_type = "IGST" if "igst" in lower else ("SGST" if "sgst" in lower else "CGST")
                _enqueue(record, "tax", lambda _i, guid, old: tally_xml_builder.build_tax_ledger_xml(
                    record.name, gst_type=gst_type, rate=record.amount, guid=guid, old_name=old),
                    company=record.company_id)
            except Exception as exc:
                _logger.warning("Tally tax enqueue skipped for %s: %s", record.id, exc)
