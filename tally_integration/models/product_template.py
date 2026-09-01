# -*- coding: utf-8 -*-
"""Outbound event hooks on product.template for syncing stock items to Tally."""
import logging
from odoo import api, models

_logger = logging.getLogger(__name__)


class ProductTemplate(models.Model):
    _inherit = "product.template"

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if not self.env.context.get("tally_no_sync"):
            for rec in records:
                rec._enqueue_tally_product()
        return records

    def write(self, vals):
        res = super().write(vals)
        if not self.env.context.get("tally_no_sync"):
            for rec in self:
                rec._enqueue_tally_product()
        return res

    def _enqueue_tally_product(self):
        self.ensure_one()
        try:
            if not self.name:
                return
            company = self.company_id or self.env.company
            instance = self.env["tally.instance"].search(
                [("company_id", "=", company.id), ("active", "=", True)], limit=1)
            if not instance:
                return
            cfg = instance.entity_config_ids.filtered(
                lambda c: c.entity == "stock_item" and c.enabled)
            if not cfg or cfg.direction not in ("odoo_to_tally", "both"):
                return

            from ..services import tally_xml_builder
            msg_xml = tally_xml_builder.build_stock_item_xml(
                name=self.name,
                base_uom=self.uom_id.name if self.uom_id else "Nos",
                parent_group=self.categ_id.name if self.categ_id else "Primary",
                hsn_code=getattr(self, "l10n_in_hsn_code", None),
                standard_cost=self.standard_price,
                sale_price=self.list_price,
            )
            envelope_xml = tally_xml_builder.wrap_import_envelope(
                [msg_xml], company_name=instance.tally_company)

            should_enqueue = self.env["tally.mapping"].register_outbound(
                instance=instance,
                entity="stock_item",
                model_name=self._name,
                res_id=self.id,
                payload_xml=envelope_xml,
            )
            if not should_enqueue:
                return

            self.env["tally.sync.queue"].create({
                "instance_id": instance.id,
                "entity": "stock_item",
                "odoo_model_name": self._name,
                "odoo_res_id": self.id,
                "idempotency_key": "odoo_product_%s_%s" % (
                    self.id, self.write_date and self.write_date.strftime("%Y%m%d%H%M%S") or ""),
                "payload": envelope_xml,
                "state": "pending",
            })
        except Exception as e:
            _logger.warning("Tally product enqueue skipped for product %s: %s", self.id, e)
