# -*- coding: utf-8 -*-
from odoo import fields, models
from .constants import ENTITY_SELECTION


class TallySyncQueue(models.Model):
    _name = "tally.sync.queue"
    _description = "Outbound Sync Queue (Odoo -> Tally)"
    _inherit = ["mail.thread"]
    _order = "create_date"

    instance_id = fields.Many2one(
        "tally.instance", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(
        related="instance_id.company_id", store=True, index=True)
    entity = fields.Selection(ENTITY_SELECTION, required=True)
    odoo_model_name = fields.Char(string="Odoo Model")
    odoo_res_id = fields.Integer(string="Odoo Record ID")
    idempotency_key = fields.Char(
        index=True, copy=False,
        help="GUID / external id ensuring a retried write is not duplicated in Tally.")
    payload = fields.Text(help="Tally-ready XML import envelope (built by the transform layer).")
    state = fields.Selection(
        [("pending", "Pending"), ("sent", "Sent to Agent"),
         ("acked", "Acknowledged"), ("failed", "Failed")],
        default="pending", tracking=True, index=True)
    attempts = fields.Integer(default=0)
    error = fields.Text()

    def action_retry(self):
        self.write({"state": "pending", "error": False})
        return True

    def action_open_record(self):
        """Open the Odoo record this queued item was built from."""
        self.ensure_one()
        if not (self.odoo_model_name and self.odoo_res_id):
            return False
        return {
            "type": "ir.actions.act_window",
            "res_model": self.odoo_model_name,
            "res_id": self.odoo_res_id,
            "view_mode": "form",
            "target": "current",
        }
