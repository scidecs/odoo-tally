# -*- coding: utf-8 -*-
"""Outbound event hooks on account.payment for syncing receipts and payments to Tally."""
import logging

from odoo import models

_logger = logging.getLogger(__name__)


class AccountPayment(models.Model):
    _inherit = "account.payment"

    def action_post(self):
        res = super().action_post()
        if not self.env.context.get("tally_no_sync"):
            for payment in self:
                payment._enqueue_tally_payment()
        return res

    def action_draft(self):
        res = super().action_draft()
        if not self.env.context.get("tally_no_sync"):
            for payment in self:
                payment._enqueue_tally_payment_cancel()
        return res

    def action_cancel(self):
        res = super().action_cancel()
        if not self.env.context.get("tally_no_sync"):
            for payment in self:
                payment._enqueue_tally_payment_cancel()
        return res

    def unlink(self):
        if not self.env.context.get("tally_no_sync"):
            for payment in self:
                payment._enqueue_tally_payment_cancel(deleting=True)
        return super().unlink()

    def _tally_entity(self):
        return "receipt" if self.payment_type == "inbound" else "payment"

    def _enqueue_tally_payment_cancel(self, deleting=False):
        """Mirror a reset/cancel/delete of a payment Tally already holds."""
        self.ensure_one()
        try:
            from ..services import tally_xml_builder
            from .tally_outbound import enqueue, target_instances, voucher_cancel_message
            entity = self._tally_entity()
            instance = target_instances(self.env, entity, self.company_id)[:1]
            if not instance:
                return
            Mapping = self.env["tally.mapping"].sudo()
            mapping = Mapping.for_record(instance, entity, self._name, self.id)
            if not mapping:
                return
            if not mapping.tally_guid:
                # Never reached Tally: withdraw the delivery instead of cancelling.
                self.env["tally.sync.queue"].sudo().search([
                    ("instance_id", "=", instance.id), ("odoo_model_name", "=", self._name),
                    ("odoo_res_id", "=", self.id), ("state", "=", "pending")]).unlink()
                if mapping.last_origin == "odoo":
                    mapping.unlink()
                return
            payload = tally_xml_builder.wrap_import_envelope(
                [voucher_cancel_message(mapping, "Receipt" if entity == "receipt" else "Payment",
                                        "%s in Odoo: %s" % ("Deleted" if deleting else "Cancelled", self.name))],
                company_name=instance.tally_company, report_type="Vouchers")
            enqueue(instance, entity, self, payload, mapping.remote_id or mapping.tally_guid,
                    key="cancel:%s:%s" % (entity, mapping.tally_guid))
        except Exception as e:
            _logger.warning("Tally payment cancel skipped for payment %s: %s", self.id, e)

    def _enqueue_tally_payment(self):
        self.ensure_one()
        try:
            from ..services import tally_xml_builder
            from .tally_outbound import (account_ledger_name, document_fingerprint, enqueue, party_ledger_name,
                                          target_instances, voucher_addressing)
            is_receipt = self.payment_type == "inbound"
            entity = self._tally_entity()
            instance = target_instances(self.env, entity, self.company_id)[:1]
            if not instance:
                return
            guid, alter_address, _mapping = voucher_addressing(instance, entity, self)
            vch_type = "Receipt" if is_receipt else "Payment"
            journal = self.journal_id
            if self.partner_id:
                self.partner_id.commercial_partner_id._enqueue_tally_party()
            if journal.default_account_id:
                journal.default_account_id._enqueue_tally_account()
            party_name = party_ledger_name(instance, self.partner_id)
            bank_or_cash = (account_ledger_name(instance, journal.default_account_id)
                            if journal.default_account_id else (journal.name or vch_type))
            pay_ref = getattr(self, "memo", False) or self.name or str(self.id)

            # Tally books are kept in the company currency.
            move = getattr(self, "move_id", False)
            amount = abs(move.amount_total_signed) if move and move.amount_total_signed else self.amount

            # Tally: credit positive. A receipt credits the party, a payment debits it.
            party_sign = 1.0 if is_receipt else -1.0
            bill_allocs = []
            remaining = amount
            invoices = self.reconciled_invoice_ids | getattr(
                self, "reconciled_bill_ids", self.env["account.move"])
            for inv in invoices:
                if remaining <= 0.005:
                    break
                applied = min(abs(inv.amount_total_signed), remaining)
                remaining -= applied
                bill_allocs.append({"type": "Agst Ref", "name": inv.name, "amount": party_sign * applied})
            if remaining > 0.005:
                bill_allocs.append({"type": "On Account", "name": pay_ref, "amount": party_sign * remaining})

            ledger_entries = [
                {"ledger": party_name, "amount": party_sign * amount, "bill_allocations": bill_allocs},
                {"ledger": bank_or_cash, "amount": -party_sign * amount},
            ]
            msg_xml = tally_xml_builder.build_voucher_xml(
                voucher_type=vch_type,
                voucher_number=self.name or str(self.id),
                date=self.date,
                party_ledger=party_name,
                ledger_entries=ledger_entries,
                narration=getattr(self, "memo", False) or self.name,
                reference=pay_ref,
                is_invoice=False,
                guid=guid,
                educational_mode=instance.tally_educational_mode,
                alter_address=alter_address,
            )
            envelope_xml = tally_xml_builder.wrap_import_envelope(
                [msg_xml], company_name=instance.tally_company, report_type="Vouchers")
            enqueue(instance, entity, self, envelope_xml, guid, fingerprint=document_fingerprint(self))
        except Exception as e:
            _logger.warning("Tally payment enqueue skipped for payment %s: %s", self.id, e)
