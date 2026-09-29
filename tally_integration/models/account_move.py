# -*- coding: utf-8 -*-
"""Outbound event hooks on account.move for syncing invoices, bills, notes and journals to Tally.

Lifecycle kept identical in both books:
* post           -> Tally Create (first time) or in-place Alter (known voucher)
* reset to draft -> Tally Cancel (a draft is not in Odoo's books either)
* cancel         -> Tally Cancel
* re-post        -> Tally Alter, which also restores a cancelled voucher
"""
import logging

from odoo import models
from odoo.tools import html2plaintext

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

    def button_draft(self):
        res = super().button_draft()
        if not self.env.context.get("tally_no_sync"):
            for move in self:
                move._enqueue_tally_cancel()
        return res

    def button_cancel(self):
        res = super().button_cancel()
        if not self.env.context.get("tally_no_sync"):
            for move in self:
                move._enqueue_tally_cancel()
        return res

    def unlink(self):
        if not self.env.context.get("tally_no_sync"):
            for move in self:
                move._enqueue_tally_cancel(deleting=True)
        return super().unlink()

    # ----------------------------------------------------------------- helpers
    def _tally_entity(self):
        entity = _ENTITY_MAP.get(self.move_type)
        if not entity:
            return False
        # Payments push themselves; bank-statement entries are matched in the
        # system that owns bank reconciliation and are not replicated.
        if getattr(self, "origin_payment_id", False) or getattr(self, "payment_ids", False):
            return False
        if getattr(self, "statement_line_id", False):
            return False
        return entity

    def _tally_instance(self, entity):
        from .tally_outbound import target_instances
        return target_instances(self.env, entity, self.company_id)[:1]

    def _enqueue_tally_cancel(self, deleting=False):
        """Mirror a reset/cancel/delete of a document Tally already holds."""
        self.ensure_one()
        try:
            entity = self._tally_entity()
            if not entity:
                return
            instance = self._tally_instance(entity)
            if not instance:
                return
            from ..services import tally_xml_builder
            from .tally_outbound import enqueue, voucher_cancel_message
            Mapping = self.env["tally.mapping"].sudo()
            mapping = Mapping.for_record(instance, entity, self._name, self.id)
            if not mapping:
                return
            Queue = self.env["tally.sync.queue"].sudo()
            pending = Queue.search([
                ("instance_id", "=", instance.id), ("odoo_model_name", "=", self._name),
                ("odoo_res_id", "=", self.id), ("state", "=", "pending")])
            if not mapping.tally_guid:
                # Never reached Tally: withdraw the delivery instead of cancelling.
                pending.unlink()
                if mapping.last_origin == "odoo":
                    mapping.unlink()
                return
            payload = tally_xml_builder.wrap_import_envelope(
                [voucher_cancel_message(mapping, _VCH_TYPE.get(entity, "Journal"),
                                        "%s in Odoo: %s" % ("Deleted" if deleting else "Cancelled", self.name))],
                company_name=instance.tally_company, report_type="Vouchers")
            enqueue(instance, entity, self, payload, mapping.remote_id or mapping.tally_guid,
                    key="cancel:%s:%s" % (entity, mapping.tally_guid))
        except Exception as e:
            _logger.warning("Tally voucher cancel skipped for move %s: %s", self.id, e)

    def _enqueue_tally_voucher(self):
        self.ensure_one()
        try:
            entity = self._tally_entity()
            if not entity:
                return
            instance = self._tally_instance(entity)
            if not instance:
                return
            from ..services import tally_xml_builder
            from .tally_outbound import (account_ledger_name, document_fingerprint, enqueue, party_ledger_name,
                                          tally_name, voucher_addressing)
            guid, alter_address, _mapping = voucher_addressing(instance, entity, self)
            vch_type = _VCH_TYPE.get(entity, "Journal")
            accounts_only = instance.tally_inventory == "accounts_only"
            same_currency = self.currency_id == self.company_id.currency_id

            # Vouchers may reference ledgers that predate connector setup. Queue
            # every dependency explicitly so first-time synchronization works.
            for account in self.line_ids.account_id:
                account._enqueue_tally_account()
            for partner in self.line_ids.partner_id.commercial_partner_id | self.partner_id.commercial_partner_id:
                partner._enqueue_tally_party()
            for product in self.invoice_line_ids.product_id:
                product.product_tmpl_id._enqueue_tally_product()
            for tax in self.line_ids.tax_line_id | self.invoice_line_ids.tax_ids:
                tax._enqueue_tally_tax()

            # Tally amount = -(Odoo balance in company currency): debit negative,
            # credit positive, identical for invoices, refunds and journals.
            ledger_entries = []
            inventory_entries = []
            party_name = party_ledger_name(instance, self.partner_id)

            def _line_ledger(line):
                if (line.account_id.account_type in ("asset_receivable", "liability_payable")
                        and line.partner_id):
                    return party_ledger_name(instance, line.partner_id)
                if line.tax_line_id:
                    return tally_name(instance, "tax", line.tax_line_id,
                                      fallback=line.tax_line_id.name)
                return account_ledger_name(instance, line.account_id)

            if self.move_type == "entry":
                for line in self.line_ids.filtered(lambda l: not l.company_currency_id.is_zero(l.balance)):
                    entry = {"ledger": _line_ledger(line), "amount": -line.balance}
                    if line.partner_id and line.account_id.account_type in ("asset_receivable", "liability_payable"):
                        entry["bill_allocations"] = [{"type": "On Account", "name": self.name, "amount": -line.balance}]
                    ledger_entries.append(entry)
                party_name = ""
            else:
                party_lines = self.line_ids.filtered(
                    lambda l: l.account_id.account_type in ("asset_receivable", "liability_payable"))
                party_amt = -sum(party_lines.mapped("balance"))
                ledger_entries.append({
                    "ledger": party_name,
                    "amount": party_amt,
                    "bill_allocations": [{
                        "type": "New Ref",
                        "name": self.name or self.ref or str(self.id),
                        "amount": party_amt,
                    }],
                })
                for line in self.invoice_line_ids.filtered(lambda l: l.display_type in (False, "product")):
                    ledger = account_ledger_name(instance, line.account_id)
                    line_amt = -line.balance
                    if line.product_id and not accounts_only:
                        qty = line.quantity or 1.0
                        if same_currency:
                            rate, discount = line.price_unit, line.discount or 0.0
                        else:
                            rate, discount = abs(line.balance) / qty, 0.0
                        inventory_entries.append({
                            "item": tally_name(instance, "stock_item", line.product_id,
                                               fallback=line.product_id.name),
                            "qty": qty,
                            "rate": rate,
                            "amount": line_amt,
                            "uom": tally_xml_builder.normalize_tally_uom(
                                line.product_uom_id.name if line.product_uom_id else "Nos"),
                            "discount": discount,
                            "account_ledger": ledger,
                        })
                    else:
                        ledger_entries.append({"ledger": ledger, "amount": line_amt})
                product_lines = self.invoice_line_ids.filtered(lambda l: l.display_type in (False, "product"))
                # Everything else (taxes, cash rounding, early-payment discount...)
                # goes line by line so the Tally voucher balances by construction.
                # Anglo-saxon COGS lines net to zero and are not part of the voucher.
                for line in (self.line_ids - party_lines - product_lines).filtered(
                        lambda l: l.display_type not in ("cogs", "line_section", "line_note")
                        and not l.company_currency_id.is_zero(l.balance)):
                    ledger_entries.append({"ledger": _line_ledger(line), "amount": -line.balance})

            msg_xml = tally_xml_builder.build_voucher_xml(
                voucher_type=vch_type,
                voucher_number=self.name or self.ref or ("INV/%s" % self.id),
                date=self.invoice_date or self.date,
                party_ledger=party_name,
                ledger_entries=ledger_entries,
                inventory_entries=inventory_entries,
                narration=html2plaintext(self.narration) if self.narration else self.ref,
                reference=self.ref if entity in ("purchase", "debit_note") and self.ref else self.name,
                is_invoice=(self.move_type != "entry"),
                guid=guid,
                educational_mode=instance.tally_educational_mode,
                alter_address=alter_address,
            )
            envelope_xml = tally_xml_builder.wrap_import_envelope(
                [msg_xml], company_name=instance.tally_company, report_type="Vouchers")
            enqueue(instance, entity, self, envelope_xml, guid, fingerprint=document_fingerprint(self))
        except Exception as e:
            _logger.warning("Tally voucher enqueue skipped for move %s: %s", self.id, e)


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    def _tally_refresh_payments(self):
        """A payment is posted before it is matched to invoices; once matched
        (or unmatched) its Tally voucher must carry the right bill references."""
        if self.env.context.get("tally_no_sync"):
            return
        payments = self.move_id.origin_payment_id
        for payment in payments.filtered(lambda p: p.state not in ("draft", "cancel")):
            payment._enqueue_tally_payment()

    def _tally_reconciled_lines(self):
        return self | self.matched_debit_ids.debit_move_id | self.matched_credit_ids.credit_move_id

    def reconcile(self):
        res = super().reconcile()
        self._tally_reconciled_lines()._tally_refresh_payments()
        return res

    def remove_move_reconcile(self):
        lines = self._tally_reconciled_lines()
        res = super().remove_move_reconcile()
        lines.exists()._tally_refresh_payments()
        return res
