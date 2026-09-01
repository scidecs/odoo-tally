# -*- coding: utf-8 -*-
"""Outbound event hooks on account.payment for syncing receipts and payments to Tally."""
import logging
from odoo import api, fields, models
from ..services import tally_xml_builder

_logger = logging.getLogger(__name__)


class AccountPayment(models.Model):
    _inherit = "account.payment"

    def action_post(self):
        res = super(AccountPayment, self).action_post()
        for payment in self:
            payment._enqueue_tally_payment()
        return res

    def _enqueue_tally_payment(self):
        """Build and enqueue Tally payment or receipt voucher XML."""
        self.ensure_one()
        instance = self.env["tally.instance"].search([
            ("company_id", "=", self.company_id.id),
            ("active", "=", True),
        ], limit=1)
        if not instance:
            return

        is_receipt = self.payment_type == "inbound"
        entity = "receipt" if is_receipt else "payment"
        vch_type = "Receipt" if is_receipt else "Payment"

        cfg = instance.entity_config_ids.filtered(lambda c: c.entity == entity and c.enabled)
        if not cfg or cfg.direction not in ("odoo_to_tally", "both"):
            return

        party_name = self.partner_id.name or "Cash"
        bank_or_cash = self.journal_id.name or ("Bank" if self.journal_id.type == "bank" else "Cash")

        # In Tally:
        # Receipt: Bank/Cash is Debited (+), Party is Credited (-)
        # Payment: Party is Debited (+), Bank/Cash is Credited (-)
        if is_receipt:
            ledger_entries = [
                {
                    "ledger": party_name,
                    "amount": self.amount,
                    "bill_allocations": [{
                        "type": "Agst Ref" if self.ref else "On Account",
                        "name": self.ref or self.name or str(self.id),
                        "amount": self.amount,
                    }],
                },
                {
                    "ledger": bank_or_cash,
                    "amount": -self.amount,
                }
            ]
        else:
            ledger_entries = [
                {
                    "ledger": party_name,
                    "amount": -self.amount,
                    "bill_allocations": [{
                        "type": "Agst Ref" if self.ref else "On Account",
                        "name": self.ref or self.name or str(self.id),
                        "amount": -self.amount,
                    }],
                },
                {
                    "ledger": bank_or_cash,
                    "amount": self.amount,
                }
            ]

        msg_xml = tally_xml_builder.build_voucher_xml(
            voucher_type=vch_type,
            voucher_number=self.name or str(self.id),
            date=self.date,
            party_ledger=party_name,
            ledger_entries=ledger_entries,
            narration=self.memo or self.ref,
            reference=self.ref,
            is_invoice=False,
        )
        envelope_xml = tally_xml_builder.wrap_import_envelope([msg_xml], company_name=instance.tally_company)

        idempotency_key = f"odoo_payment_{self.id}_{self.write_date.strftime('%Y%m%d%H%M%S') if self.write_date else ''}"
        self.env["tally.sync.queue"].create({
            "instance_id": instance.id,
            "entity": entity,
            "odoo_model_name": self._name,
            "odoo_res_id": self.id,
            "idempotency_key": idempotency_key,
            "payload": envelope_xml,
            "state": "pending",
        })
