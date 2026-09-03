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
            party_name = self.partner_id.name or "Cash"
            journal = self.journal_id
            bank_or_cash = (journal.default_account_id.name if journal.default_account_id else None) or journal.name or ("Bank" if journal.type == "bank" else "Cash")
            # account.payment has no 'ref' field in recent Odoo; use memo/name safely.
            pay_ref = getattr(self, "memo", False) or self.name or str(self.id)
            alloc_type = "Agst Ref" if pay_ref else "On Account"

            if is_receipt:
                ledger_entries = [
                    {"ledger": party_name, "amount": self.amount,
                     "bill_allocations": [{"type": alloc_type, "name": pay_ref, "amount": self.amount}]},
                    {"ledger": bank_or_cash, "amount": -self.amount},
                ]
            else:
                ledger_entries = [
                    {"ledger": party_name, "amount": -self.amount,
                     "bill_allocations": [{"type": alloc_type, "name": pay_ref, "amount": -self.amount}]},
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
            )
            envelope_xml = tally_xml_builder.wrap_import_envelope(
                [msg_xml], company_name=instance.tally_company, report_type="Vouchers")

            should_enqueue = self.env["tally.mapping"].register_outbound(
                instance=instance,
                entity=entity,
                model_name=self._name,
                res_id=self.id,
                payload_xml=envelope_xml,
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
