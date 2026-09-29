# -*- coding: utf-8 -*-
"""Outbound internal stock transfers as Tally Stock Journal vouchers."""
import logging

from odoo import models

from .compat import move_uom_field

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
        from .tally_outbound import (document_fingerprint, enqueue, godown_name, tally_name, target_instances,
                                     voucher_addressing)
        for picking in self:
            try:
                instance = target_instances(self.env, "stock_journal", picking.company_id)[:1]
                if not instance:
                    continue
                guid, alter_address, _mapping = voucher_addressing(instance, "stock_journal", picking)
                for location in picking.move_ids.location_id | picking.move_ids.location_dest_id:
                    location._enqueue_tally_godown()
                for product in picking.move_ids.product_id:
                    product.product_tmpl_id._enqueue_tally_product()
                uom_field = move_uom_field(self.env)
                entries = []
                for move in picking.move_ids.filtered(lambda m: m.state == "done"):
                    qty = move.quantity
                    if not qty:
                        continue
                    rate = move.product_id.standard_price
                    common = {
                        "item": tally_name(instance, "stock_item", move.product_id,
                                           fallback=move.product_id.name),
                        "rate": rate,
                        "uom": tally_xml_builder.normalize_tally_uom(move[uom_field].name),
                    }
                    entries.extend([
                        # The OUT collection determines movement direction in
                        # Tally; quantity itself remains positive.
                        dict(common, qty=qty, amount=-(qty * rate),
                             godown=godown_name(instance, move.location_id)),
                        dict(common, qty=qty, amount=qty * rate,
                             godown=godown_name(instance, move.location_dest_id)),
                    ])
                if not entries:
                    continue
                message = tally_xml_builder.build_voucher_xml(
                    voucher_type="Stock Journal", voucher_number=picking.name,
                    date=picking.date_done or picking.scheduled_date,
                    party_ledger="", inventory_entries=entries,
                    narration=picking.origin or picking.note, is_invoice=False, guid=guid,
                    educational_mode=instance.tally_educational_mode,
                    alter_address=alter_address)
                payload = tally_xml_builder.wrap_import_envelope(
                    [message], company_name=instance.tally_company, report_type="Vouchers")
                enqueue(instance, "stock_journal", picking, payload, guid, fingerprint=document_fingerprint(picking))
            except Exception as exc:
                _logger.warning("Tally stock-journal enqueue skipped for %s: %s", picking.id, exc)
