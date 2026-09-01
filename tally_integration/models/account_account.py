# -*- coding: utf-8 -*-
"""Outbound event hooks on account.account for syncing chart of accounts to Tally."""
import logging
from odoo import api, fields, models
from ..services import tally_xml_builder

_logger = logging.getLogger(__name__)


class AccountAccount(models.Model):
    _inherit = "account.account"

    @api.model_create_multi
    def create(self, vals_list):
        records = super(AccountAccount, self).create(vals_list)
        for rec in records:
            rec._enqueue_tally_account()
        return records

    def write(self, vals):
        res = super(AccountAccount, self).write(vals)
        for rec in self:
            rec._enqueue_tally_account()
        return res

    def _enqueue_tally_account(self):
        """Enqueue account ledger into Tally sync queue."""
        self.ensure_one()
        if not self.name:
            return

        company = self.company_id or self.env.company
        instance = self.env["tally.instance"].search([
            ("company_id", "=", company.id),
            ("active", "=", True),
        ], limit=1)
        if not instance:
            return

        cfg = instance.entity_config_ids.filtered(lambda c: c.entity == "account_ledger" and c.enabled)
        if not cfg or cfg.direction not in ("odoo_to_tally", "both"):
            return

        # Map account type to default Tally group
        type_to_group = {
            "asset_receivable": "Sundry Debtors",
            "asset_cash": "Bank Accounts",
            "asset_current": "Current Assets",
            "asset_fixed": "Fixed Assets",
            "liability_payable": "Sundry Creditors",
            "liability_current": "Current Liabilities",
            "equity": "Capital Account",
            "income": "Direct Incomes",
            "income_other": "Indirect Incomes",
            "expense": "Indirect Expenses",
            "expense_direct_cost": "Direct Expenses",
        }
        parent_group = type_to_group.get(self.account_type, "Indirect Expenses")

        msg_xml = tally_xml_builder.build_account_ledger_xml(
            name=self.name,
            parent=parent_group,
            currency=self.currency_id.name if self.currency_id else "INR",
        )
        envelope_xml = tally_xml_builder.wrap_import_envelope([msg_xml], company_name=instance.tally_company)

        idempotency_key = f"odoo_account_{self.id}_{self.write_date.strftime('%Y%m%d%H%M%S') if self.write_date else ''}"
        self.env["tally.sync.queue"].create({
            "instance_id": instance.id,
            "entity": "account_ledger",
            "odoo_model_name": self._name,
            "odoo_res_id": self.id,
            "idempotency_key": idempotency_key,
            "payload": envelope_xml,
            "state": "pending",
        })
