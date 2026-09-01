# -*- coding: utf-8 -*-
"""Outbound event hooks on product.template for syncing products to Tally."""
import logging
from odoo import api, fields, models
from ..services import tally_xml_builder

_logger = logging.getLogger(__name__)


class ProductTemplate(models.Model):
    _inherit = "product.template"

    @api.model_create_multi
    def create(self, vals_list):
        records = super(ProductTemplate, self).create(vals_list)
        for rec in records:
            rec._enqueue_tally_product()
        return records

    def write(self, vals):
        res = super(ProductTemplate, self).write(vals)
        for rec in self:
            rec._enqueue_tally_product()
        return res

    def _enqueue_tally_product(self):
        """Enqueue stock item into Tally sync queue."""
        self.ensure_one()
        if not self.name:
            return

        company = self.company_id or self.env.company
        instance = self.env["tally.instance"].search([
            ("company_id", "=", company.id),
            ("active", "=", True),
        ], limit=1)
        if not instance:
            return

        cfg = instance.entity_config_ids.filtered(lambda c: c.entity == "stock_item" and c.enabled)
        if not cfg or cfg.direction not in ("odoo_to_tally", "both"):
            return

        hsn = getattr(self, "l10n_in_hsn_code", None)

        msg_xml = tally_xml_builder.build_stock_item_xml(
            name=self.name,
            base_uom=self.uom_id.name if self.uom_id else "Nos",
            parent_group=self.categ_id.name if self.categ_id else "Primary",
            hsn_code=hsn,
            standard_cost=self.standard_price,
            sale_price=self.list_price,
        )
        envelope_xml = tally_xml_builder.wrap_import_envelope([msg_xml], company_name=instance.tally_company)

        idempotency_key = f"odoo_product_{self.id}_{self.write_date.strftime('%Y%m%d%H%M%S') if self.write_date else ''}"
        self.env["tally.sync.queue"].create({
            "instance_id": instance.id,
            "entity": "stock_item",
            "odoo_model_name": self._name,
            "odoo_res_id": self.id,
            "idempotency_key": idempotency_key,
            "payload": envelope_xml,
            "state": "pending",
        })
