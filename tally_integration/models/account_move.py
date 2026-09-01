# -*- coding: utf-8 -*-
"""Outbound event hooks on account.move for syncing invoices, bills, and journals to Tally."""
import logging
from odoo import api, fields, models
from ..services import tally_xml_builder

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = "account.move"

    def action_post(self):
        res = super(AccountMove, self).action_post()
        for move in self:
            move._enqueue_tally_voucher()
        return res

    def _enqueue_tally_voucher(self):
        """Build and enqueue Tally voucher XML if sync is active and direction allows."""
        self.ensure_one()
        instance = self.env["tally.instance"].search([
            ("company_id", "=", self.company_id.id),
            ("active", "=", True),
        ], limit=1)
        if not instance:
            return

        # Determine entity type
        entity_map = {
            "out_invoice": "sales",
            "out_refund": "credit_note",
            "in_invoice": "purchase",
            "in_refund": "debit_note",
            "entry": "journal",
        }
        entity = entity_map.get(self.move_type)
        if not entity:
            return

        cfg = instance.entity_config_ids.filtered(lambda c: c.entity == entity and c.enabled)
        if not cfg or cfg.direction not in ("odoo_to_tally", "both"):
            return

        # Map to Tally voucher type
        tally_vch_type_map = {
            "sales": "Sales",
            "credit_note": "Credit Note",
            "purchase": "Purchase",
            "debit_note": "Debit Note",
            "journal": "Journal",
        }
        vch_type = tally_vch_type_map.get(entity, "Journal")

        party_name = self.partner_id.name or "Cash"

        # Build ledger and inventory entries
        ledger_entries = []
        inventory_entries = []

        # Party line / Receivable or Payable
        party_amt = self.amount_total if entity in ("sales", "debit_note") else -self.amount_total
        ledger_entries.append({
            "ledger": party_name,
            "amount": party_amt,
            "bill_allocations": [{
                "type": "New Ref",
                "name": self.name or self.ref or str(self.id),
                "amount": party_amt,
            }],
        })

        for line in self.invoice_line_ids:
            if line.product_id:
                inventory_entries.append({
                    "item": line.product_id.name,
                    "qty": line.quantity,
                    "rate": line.price_unit,
                    "amount": line.price_subtotal,
                    "uom": line.product_uom_id.name if line.product_uom_id else "Nos",
                    "discount": line.discount,
                })
            else:
                acc_name = line.account_id.name or "Sales"
                ledger_entries.append({
                    "ledger": acc_name,
                    "amount": -line.price_subtotal if entity in ("sales", "debit_note") else line.price_subtotal,
                })

        # Add Tax Lines
        for tax_line in self.line_ids.filtered(lambda l: l.tax_line_id):
            ledger_entries.append({
                "ledger": tax_line.name or tax_line.account_id.name,
                "amount": -tax_line.balance if entity in ("sales", "debit_note") else tax_line.balance,
            })

        msg_xml = tally_xml_builder.build_voucher_xml(
            voucher_type=vch_type,
            voucher_number=self.name or self.ref or f"INV/{self.id}",
            date=self.invoice_date or self.date,
            party_ledger=party_name,
            ledger_entries=ledger_entries,
            inventory_entries=inventory_entries,
            narration=self.narration or self.ref,
            reference=self.ref,
            is_invoice=(self.move_type != "entry"),
        )
        envelope_xml = tally_xml_builder.wrap_import_envelope([msg_xml], company_name=instance.tally_company)

        # Enqueue
        idempotency_key = f"odoo_move_{self.id}_{self.write_date.strftime('%Y%m%d%H%M%S') if self.write_date else ''}"
        self.env["tally.sync.queue"].create({
            "instance_id": instance.id,
            "entity": entity,
            "odoo_model_name": self._name,
            "odoo_res_id": self.id,
            "idempotency_key": idempotency_key,
            "payload": envelope_xml,
            "state": "pending",
        })
