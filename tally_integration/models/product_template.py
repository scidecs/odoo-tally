# -*- coding: utf-8 -*-
"""Outbound event hooks on product.template for syncing stock items to Tally."""
import logging
from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class ProductTemplate(models.Model):
    _inherit = "product.template"
    TALLY_FIELDS = {"name", "uom_id", "categ_id", "l10n_in_hsn_code", "standard_price", "list_price", "default_code", "barcode", "type", "is_storable"}

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if not self.env.context.get("tally_no_sync"):
            for rec in records:
                rec._enqueue_tally_product()
        return records

    def write(self, vals):
        res = super().write(vals)
        if not self.env.context.get("tally_no_sync") and self.TALLY_FIELDS.intersection(vals):
            for rec in self:
                rec._enqueue_tally_product()
        return res

    def _enqueue_tally_product(self):
        self.ensure_one()
        try:
            if not self.name:
                return
            identity = self.product_variant_id
            if not identity:
                return
            from ..services import tally_xml_builder
            from .tally_outbound import enqueue, target_instances
            Mapping = self.env["tally.mapping"].sudo()
            # Tally rejects a stock item whose base unit does not exist yet.
            if self.uom_id:
                self.uom_id._enqueue_tally_uom()
            for instance in target_instances(self.env, "stock_item", self.company_id):
                # Inbound stock items map to product.product. Migrate a legacy
                # template-level mapping so one product keeps one Tally identity.
                legacy = Mapping.for_record(instance, "stock_item", self._name, self.id)
                if legacy and not Mapping.for_record(instance, "stock_item", identity._name, identity.id):
                    legacy.write({"odoo_model_name": identity._name, "odoo_res_id": identity.id})
                address = Mapping.outbound_address(instance, "stock_item", identity._name, identity.id)
                guid = Mapping.outbound_guid(instance, "stock_item", identity._name, identity.id)
                base_uom = tally_xml_builder.normalize_tally_uom(
                    self.uom_id.name if self.uom_id else "Nos")
                rate_date = fields.Date.context_today(self)
                if instance.tally_educational_mode:
                    rate_date = rate_date.replace(day=1)
                # A known item is altered in place (Tally may reset structural
                # fields such as PARENT when an existing name is re-sent as Create).
                msg_xml = tally_xml_builder.build_stock_item_xml(
                    name=self.name,
                    base_uom=base_uom,
                    parent_group=self.categ_id.name if self.categ_id else "Primary",
                    hsn_code=getattr(self, "l10n_in_hsn_code", None),
                    standard_cost=self.standard_price,
                    sale_price=self.list_price,
                    guid=guid,
                    part_no=identity.default_code,
                    barcode=identity.barcode,
                    effective_date=rate_date,
                    action="Alter" if address["bound"] else "Create",
                    old_name=address["name"] or None,
                )
                envelope_xml = tally_xml_builder.wrap_import_envelope(
                    [msg_xml], company_name=instance.tally_company)
                enqueue(instance, "stock_item", identity, envelope_xml, guid,
                        tally_name_value=self.name, allow_tally_origin=True)
        except Exception as e:
            _logger.warning("Tally product enqueue skipped for product %s: %s", self.id, e)


class ProductProduct(models.Model):
    _inherit = "product.product"
    TALLY_FIELDS = {"name", "default_code", "barcode", "standard_price", "lst_price"}

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if not self.env.context.get("tally_no_sync"):
            for rec in records:
                rec.product_tmpl_id._enqueue_tally_product()
        return records

    def write(self, vals):
        res = super().write(vals)
        if not self.env.context.get("tally_no_sync") and self.TALLY_FIELDS.intersection(vals):
            for rec in self:
                rec.product_tmpl_id._enqueue_tally_product()
        return res
