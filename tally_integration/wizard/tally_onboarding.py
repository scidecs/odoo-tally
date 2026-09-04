# -*- coding: utf-8 -*-
from odoo import _, fields, models


class TallyOnboarding(models.TransientModel):
    """Initial full-sync / migration wizard for a client already live on Tally.

    Configures the CoA mode and the initial pull scope, resets AlterID watermarks
    so the next agent poll performs a FULL export, and records the onboarding start.
    The heavy transform/upsert is performed by the sync engine + agent (phased).
    """
    _name = "tally.onboarding"
    _description = "Tally Onboarding / Initial Migration"

    instance_id = fields.Many2one("tally.instance", required=True, ondelete="cascade")
    coa_mode = fields.Selection(
        [("import", "Import CoA from Tally"),
         ("map", "Map to existing Odoo CoA")],
        string="Chart of Accounts", default="import", required=True)
    sync_coa = fields.Boolean(string="Chart of Accounts & Groups", default=True)
    sync_masters = fields.Boolean(string="Masters (parties, items, units)", default=True)
    sync_opening_balance = fields.Boolean(string="Opening Balances", default=True)
    sync_history = fields.Boolean(string="Historical Vouchers", default=False)
    history_from = fields.Date(string="History From")
    configure_indian_localization = fields.Boolean(
        string="Configure Indian Localization & INR", default=True,
        help="Sets company currency to INR (₹), sets country to India, and activates Indian GST/TDS localization.")
    reset_watermarks = fields.Boolean(
        string="Force Full Pull", default=True,
        help="Reset AlterID watermarks so the next poll re-exports everything.")

    def action_start(self):
        self.ensure_one()
        instance = self.instance_id
        if self.configure_indian_localization:
            instance.action_setup_indian_localization()
        instance.write({
            "coa_mode": self.coa_mode,
            "history_from": self.history_from,
        })
        if self.reset_watermarks:
            instance.entity_config_ids.write({"last_alterid": 0})
        summary = _(
            "Onboarding started · CoA mode: %(coa)s · masters: %(m)s · "
            "opening balances: %(ob)s · history: %(h)s",
            coa=self.coa_mode,
            m="yes" if self.sync_masters else "no",
            ob="yes" if self.sync_opening_balance else "no",
            h=(self.history_from and str(self.history_from)) or "no",
        )
        self.env["tally.sync.log"].log(
            instance, "tally_to_odoo", False, "success", summary)
        instance.message_post(body=summary)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Onboarding queued"),
                "message": _("The agent will perform a full export on its next poll. "
                             "Watch progress in the Sync Logs."),
                "type": "success",
                "sticky": False,
            },
        }
