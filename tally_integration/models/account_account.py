# -*- coding: utf-8 -*-
"""Outbound event hooks on account.account for syncing the chart of accounts to Tally."""
import logging
from odoo import api, models

_logger = logging.getLogger(__name__)

_TYPE_TO_GROUP = {
    "asset_receivable": "Sundry Debtors",
    "asset_cash": "Bank Accounts",
    "asset_current": "Current Assets",
    "asset_non_current": "Investments",
    "asset_fixed": "Fixed Assets",
    "liability_payable": "Sundry Creditors",
    "liability_current": "Current Liabilities",
    "liability_non_current": "Loans (Liability)",
    "equity": "Capital Account",
    "income": "Direct Incomes",
    "income_other": "Indirect Incomes",
    "expense": "Indirect Expenses",
    "expense_direct_cost": "Direct Expenses",
}


class AccountAccount(models.Model):
    _inherit = "account.account"
    TALLY_FIELDS = {"name", "account_type", "currency_id"}

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if not self.env.context.get("tally_no_sync"):
            for rec in records:
                rec._enqueue_tally_account()
        return records

    def write(self, vals):
        res = super().write(vals)
        if not self.env.context.get("tally_no_sync") and self.TALLY_FIELDS.intersection(vals):
            for rec in self:
                rec._enqueue_tally_account()
        return res

    def _tally_is_clearing_account(self):
        """Odoo-only clearing accounts (outstanding receipts/payments, internal
        transfer, bank suspense) have no Tally equivalent: Tally posts payments
        straight to the bank ledger."""
        companies = self.company_ids if "company_ids" in self._fields else self.company_id
        for company in companies:
            for fname in ("account_journal_payment_debit_account_id", "account_journal_payment_credit_account_id",
                          "transfer_account_id", "account_journal_suspense_account_id"):
                if fname in company._fields and company[fname] == self:
                    return True
        return bool(self.env["account.payment.method.line"].sudo().search_count(
            [("payment_account_id", "=", self.id)]))

    def _enqueue_tally_account(self):
        self.ensure_one()
        try:
            if not self.name:
                return
            # Receivable/payable control accounts are represented in Tally by the
            # individual party ledgers, never by a ledger of their own.
            if self.account_type in ("asset_receivable", "liability_payable", "off_balance"):
                return
            if self._tally_is_clearing_account():
                return
            from ..services import tally_xml_builder
            from .tally_outbound import enqueue, target_instances
            companies = (self.company_ids if "company_ids" in self._fields
                         else getattr(self, "company_id", self.env["res.company"]))
            Mapping = self.env["tally.mapping"].sudo()
            for instance in target_instances(self.env, "account_ledger", companies):
                guid = Mapping.outbound_guid(instance, "account_ledger", self._name, self.id)
                old_name = Mapping.outbound_address(
                    instance, "account_ledger", self._name, self.id).get("name")
                known = instance._get_ledger_index().get((old_name or self.name).strip().lower(), {})
                parent_group = known.get("parent") or _TYPE_TO_GROUP.get(self.account_type, "Indirect Expenses")
                if self.account_type == "asset_cash" and not known:
                    journal = self.env["account.journal"].sudo().search(
                        [("default_account_id", "=", self.id)], limit=1)
                    parent_group = "Cash-in-Hand" if journal.type == "cash" else "Bank Accounts"
                msg_xml = tally_xml_builder.build_account_ledger_xml(
                    name=self.name,
                    parent=parent_group,
                    currency=self.currency_id.name if self.currency_id else None,
                    # Tally only lets a ledger carry item allocations in invoice
                    # mode when "inventory values are affected".
                    affects_stock=self.account_type in (
                        "income", "income_other", "expense", "expense_direct_cost"),
                    guid=guid,
                    old_name=old_name,
                )
                envelope_xml = tally_xml_builder.wrap_import_envelope(
                    [msg_xml], company_name=instance.tally_company)
                enqueue(instance, "account_ledger", self, envelope_xml, guid,
                        tally_name_value=self.name, allow_tally_origin=True)
        except Exception as e:
            _logger.warning("Tally account enqueue skipped for account %s: %s", self.id, e)
