# -*- coding: utf-8 -*-
"""Outbound internal stock transfers as Tally Stock Journal vouchers."""
import logging

from odoo import models

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def button_validate(self):
        result = super().button_validate()
        if not self.env.context.get("tally_no_sync"):
            self.filtered(lambda p: p.state == "done" and p.picking_type_id.code == "internal")._enqueue_tally_stock_journal()
        return result

    def _enqueue_tally_stock_journal(self):
        from ..services import tally_xml_builder
        for picking in self:
            try:
                instance = self.env["tally.instance"].search([
                    ("company_id", "=", picking.company_id.id), ("active", "=", True),
                ], limit=1)
                cfg = instance.entity_config_ids.filtered(
                    lambda c: c.entity == "stock_journal" and c.enabled
                    and c.direction in ("odoo_to_tally", "both"))[:1]
                if not instance or not cfg:
                    continue
                guid = self.env["tally.mapping"].outbound_guid(
                    instance, "stock_journal", picking._name, picking.id)
                for location in picking.location_id | picking.location_dest_id:
                    location._enqueue_tally_godown()
                for product in picking.move_ids.product_id:
                    product.product_tmpl_id._enqueue_tally_product()
                entries = []
                for move in picking.move_ids.filtered(lambda m: m.state == "done"):
                    qty = move.quantity
                    if not qty:
                        continue
                    rate = move.product_id.standard_price
                    common = {
                        "item": move.product_id.name,
                        "rate": rate,
                        "uom": tally_xml_builder.normalize_tally_uom(move.product_uom.name),
                    }
                    entries.extend([
                        # The OUT collection determines movement direction in
                        # Tally; quantity itself remains positive.
                        dict(common, qty=qty, amount=-(qty * rate),
                             godown=move.location_id.name),
                        dict(common, qty=qty, amount=qty * rate,
                             godown=move.location_dest_id.name),
                    ])
                if not entries:
                    continue
                message = tally_xml_builder.build_voucher_xml(
                    voucher_type="Stock Journal", voucher_number=picking.name,
                    date=picking.date_done or picking.scheduled_date,
                    party_ledger="", inventory_entries=entries,
                    narration=picking.origin or picking.note, is_invoice=False, guid=guid,
                    educational_mode=instance.tally_educational_mode)
                payload = tally_xml_builder.wrap_import_envelope(
                    [message], company_name=instance.tally_company, report_type="Vouchers")
                if not self.env["tally.mapping"].register_outbound(
                        instance, "stock_journal", picking._name, picking.id, payload,
                        guid=guid):
                    continue
                self.env["tally.sync.queue"].create({
                    "instance_id": instance.id, "entity": "stock_journal",
                    "odoo_model_name": picking._name, "odoo_res_id": picking.id,
                    "idempotency_key": "stock_journal:%s" % guid,
                    "payload": payload, "state": "pending",
                })
            except Exception as exc:
                _logger.warning("Tally stock-journal enqueue skipped for %s: %s", picking.id, exc)
