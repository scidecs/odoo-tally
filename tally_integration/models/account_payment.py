# -*- coding: utf-8 -*-
"""Outbound event hooks on account.payment for syncing receipts and payments to Tally."""
import logging
from odoo import api, models

_logger = logging.getLogger(__name__)


class AccountPayment(models.Model):
    _inherit = "account.payment"

    def action_post(self):
        res = super().action_post()
        if not self.env.context.get("tally_no_sync"):
            for payment in self:
                payment._enqueue_tally_payment()
        return res

    def _enqueue_tally_payment(self):
        self.ensure_one()
        try:
            instance = self.env["tally.instance"].search(
                [("company_id", "=", self.company_id.id), ("active", "=", True)], limit=1)
            if not instance:
                return
            is_receipt = self.payment_type == "inbound"
            entity = "receipt" if is_receipt else "payment"
            vch_type = "Receipt" if is_receipt else "Payment"
            cfg = instance.entity_config_ids.filtered(
                lambda c: c.entity == entity and c.enabled)
            if not cfg or cfg.direction not in ("odoo_to_tally", "both"):
                return

            from ..services import tally_xml_builder
            guid = self.env["tally.mapping"].outbound_guid(
                instance, entity, self._name, self.id)
            party_name = self.partner_id.name or "Cash"
            journal = self.journal_id
            pay_ref = getattr(self, "memo", False) or self.name or str(self.id)

            if self.partner_id:
                self.partner_id._enqueue_tally_party()
            if journal.default_account_id:
                journal.default_account_id._enqueue_tally_account()

            # Resolve mapped Tally bank/cash ledger name
            bank_or_cash = None
            if journal.default_account_id:
                mapping = self.env["tally.mapping"].search([
                    ("instance_id", "=", instance.id),
                    ("odoo_model_name", "=", "account.account"),
                    ("odoo_res_id", "=", journal.default_account_id.id),
                ], limit=1)
                if mapping and mapping.tally_guid and not mapping.tally_guid.startswith("odoo_"):
                    # Tally's display name is not stored separately in the identity map.
                    # The Odoo account name is the canonical outbound ledger name.
                    bank_or_cash = journal.default_account_id.name
                else:
                    bank_or_cash = journal.default_account_id.name

            if not bank_or_cash:
                bank_or_cash = journal.name or ("Bank" if journal.type == "bank" else "Cash")

            # Build real bill allocations from reconciled invoices/bills
            bill_allocs = []
            reconciled_moves = self.reconciled_invoice_ids or getattr(self, "reconciled_bill_ids", self.env["account.move"])
            if reconciled_moves:
                for inv in reconciled_moves:
                    inv_ref = inv.ref or inv.name
                    bill_allocs.append({
                        "type": "Agst Ref",
                        "name": inv_ref,
                        "amount": self.amount if is_receipt else -self.amount,
                    })

            if not bill_allocs:
                alloc_type = "Agst Ref" if getattr(self, "memo", False) else "On Account"
                bill_allocs.append({
                    "type": alloc_type,
                    "name": pay_ref,
                    "amount": self.amount if is_receipt else -self.amount,
                })

            if is_receipt:
                ledger_entries = [
                    {"ledger": party_name, "amount": self.amount, "bill_allocations": bill_allocs},
                    {"ledger": bank_or_cash, "amount": -self.amount},
                ]
            else:
                ledger_entries = [
                    {"ledger": party_name, "amount": -self.amount, "bill_allocations": bill_allocs},
                    {"ledger": bank_or_cash, "amount": self.amount},
                ]

            msg_xml = tally_xml_builder.build_voucher_xml(
                voucher_type=vch_type,
                voucher_number=self.name or str(self.id),
                date=self.date,
                party_ledger=party_name,
                ledger_entries=ledger_entries,
                narration=getattr(self, "memo", False),
                reference=pay_ref,
                is_invoice=False,
                guid=guid,
                educational_mode=instance.tally_educational_mode,
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
                "idempotency_key": "odoo_payment_%s_%s" % (
                    self.id, self.write_date and self.write_date.strftime("%Y%m%d%H%M%S") or ""),
                "payload": envelope_xml,
                "state": "pending",
            })
        except Exception as e:
            _logger.warning("Tally payment enqueue skipped for payment %s: %s", self.id, e)
