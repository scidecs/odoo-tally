# -*- coding: utf-8 -*-
"""Outbound event hooks on account.move for syncing invoices, bills, notes and journals to Tally."""
import logging
from odoo import api, models

_logger = logging.getLogger(__name__)

_ENTITY_MAP = {
    "out_invoice": "sales",
    "out_refund": "credit_note",
    "in_invoice": "purchase",
    "in_refund": "debit_note",
    "entry": "journal",
}
_VCH_TYPE = {
    "sales": "Sales", "credit_note": "Credit Note",
    "purchase": "Purchase", "debit_note": "Debit Note", "journal": "Journal",
}


class AccountMove(models.Model):
    _inherit = "account.move"

    def action_post(self):
        res = super().action_post()
        if not self.env.context.get("tally_no_sync"):
            for move in self:
                move._enqueue_tally_voucher()
        return res

    def _enqueue_tally_voucher(self):
        self.ensure_one()
        try:
            entity = _ENTITY_MAP.get(self.move_type)
            if not entity or getattr(self, "origin_payment_id", False) or getattr(self, "payment_ids", False):
                return
            instance = self.env["tally.instance"].search(
                [("company_id", "=", self.company_id.id), ("active", "=", True)], limit=1)
            if not instance:
                return
            cfg = instance.entity_config_ids.filtered(
                lambda c: c.entity == entity and c.enabled)
            if not cfg or cfg.direction not in ("odoo_to_tally", "both"):
                return

            from ..services import tally_xml_builder
            guid = self.env["tally.mapping"].outbound_guid(
                instance, entity, self._name, self.id)
            vch_type = _VCH_TYPE.get(entity, "Journal")
            party_name = self.partner_id.name or "Cash"
            accounts_only = instance.tally_inventory == "accounts_only"

            ledger_entries = []
            inventory_entries = []

            if self.move_type == "entry":
                # General Journal Entry (multi-line double-entry)
                for line in self.line_ids:
                    acc_name = line.account_id.name or (line.partner_id.name if line.partner_id else "Suspense")
                    amt = -line.debit if line.debit else line.credit
                    ledger_entries.append({
                        "ledger": acc_name,
                        "amount": amt,
                    })
            else:
                # Party line (Receivable / Payable)
                is_debit_party = entity in ("sales", "debit_note")
                party_amt = -self.amount_total if is_debit_party else self.amount_total
                ledger_entries.append({
                    "ledger": party_name,
                    "amount": party_amt,
                    "bill_allocations": [{
                        "type": "New Ref",
                        "name": self.name or self.ref or str(self.id),
                        "amount": party_amt,
                    }],
                })

                default_acc = "Sales Account" if is_debit_party else "Purchase Account"
                for line in self.invoice_line_ids:
                    acc_name = (line.account_id.name if line.account_id else None) or default_acc
                    line_amt = line.price_subtotal if is_debit_party else -line.price_subtotal

                    if line.product_id and not accounts_only:
                        inventory_entries.append({
                            "item": line.product_id.name,
                            "qty": line.quantity,
                            "rate": line.price_unit,
                            "amount": line_amt,
                            "uom": line.product_uom_id.name if line.product_uom_id else "Nos",
                            "discount": getattr(line, "discount", 0.0),
                            "account_ledger": acc_name,
                        })
                    else:
                        ledger_entries.append({
                            "ledger": acc_name,
                            "amount": line_amt,
                        })

                for tax_line in self.line_ids.filtered(lambda l: l.tax_line_id):
                    tax_acc = tax_line.name or (tax_line.account_id.name if tax_line.account_id else "Duties & Taxes")
                    # Tally's voucher sign convention is the inverse of the
                    # Odoo journal-line balance for every invoice/refund type.
                    tax_amt = -tax_line.balance
                    ledger_entries.append({
                        "ledger": tax_acc,
                        "amount": tax_amt,
                    })

            msg_xml = tally_xml_builder.build_voucher_xml(
                voucher_type=vch_type,
                voucher_number=self.name or self.ref or ("INV/%s" % self.id),
                date=self.invoice_date or self.date,
                party_ledger=party_name,
                ledger_entries=ledger_entries,
                inventory_entries=inventory_entries,
                narration=self.narration or self.ref,
                reference=self.ref,
                is_invoice=(self.move_type != "entry"),
                guid=guid,
            )
            envelope_xml = tally_xml_builder.wrap_import_envelope(
                [msg_xml], company_name=instance.tally_company, report_type="Vouchers")

            should_enqueue = self.env["tally.mapping"].register_outbound(
                instance=instance,
                entity=entity,
                model_name=self._name,
                res_id=self.id,
                payload_xml=envelope_xml,
                guid=guid,
            )
            if not should_enqueue:
                return

            self.env["tally.sync.queue"].create({
                "instance_id": instance.id,
                "entity": entity,
                "odoo_model_name": self._name,
                "odoo_res_id": self.id,
                "idempotency_key": "odoo_move_%s_%s" % (
                    self.id, self.write_date and self.write_date.strftime("%Y%m%d%H%M%S") or ""),
                "payload": envelope_xml,
                "state": "pending",
            })
        except Exception as e:
            _logger.warning("Tally voucher enqueue skipped for move %s: %s", self.id, e)
