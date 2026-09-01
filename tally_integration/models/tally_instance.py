# -*- coding: utf-8 -*-
import secrets

from odoo import _, api, fields, models
from .constants import DEFAULT_ENTITIES, direction_for_source


class TallyInstance(models.Model):
    _name = "tally.instance"
    _description = "Tally Connection / Instance"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "name"

    name = fields.Char(required=True, tracking=True)
    company_id = fields.Many2one(
        "res.company", required=True, index=True,
        default=lambda self: self.env.company,
    )
    active = fields.Boolean(default=True)

    # --- Tally endpoint (reached by the on-prem agent, not by Odoo directly) ---
    tally_host = fields.Char(
        string="Tally Host", default="127.0.0.1",
        help="Host/IP where the Tally XML gateway listens, as seen by the on-prem agent.",
    )
    tally_port = fields.Integer(string="Tally Port", default=9000)
    tally_company = fields.Char(
        string="Tally Company",
        help="Exact name of the company open in TallyPrime.",
    )

    # --- Source of truth ---
    default_source = fields.Selection(
        [("tally", "Tally (accounting system)"), ("odoo", "Odoo")],
        string="Default Source of Truth", default="tally", required=True, tracking=True,
        help="Default winner on conflict for this instance. Override per entity below.",
    )
    poll_interval = fields.Integer(
        string="Poll Interval (s)", default=60,
        help="How often the on-prem agent polls Tally for AlterID changes.",
    )

    # --- Onboarding / initial migration ---
    coa_mode = fields.Selection(
        [("import", "Import CoA from Tally"),
         ("map", "Map to existing Odoo CoA")],
        string="Chart of Accounts Mode", default="import",
        help="On initial onboarding: import Tally's chart of accounts wholesale "
             "(greenfield Odoo), or map Tally ledgers onto an existing Odoo CoA.",
    )
    onboarding_done = fields.Boolean(string="Onboarding Done", readonly=True)
    history_from = fields.Date(
        string="History From",
        help="Earliest voucher date to pull on the initial full sync.")

    # --- Agent pairing / health ---
    agent_token = fields.Char(
        string="Agent Token", copy=False, readonly=True,
        groups="tally_integration.group_tally_manager",
        help="Bearer token the on-prem Sync Agent uses to authenticate. Keep secret.",
    )
    agent_last_seen = fields.Datetime(string="Agent Last Seen", readonly=True)
    state = fields.Selection(
        [("draft", "Draft"), ("online", "Online"), ("offline", "Offline")],
        default="draft", readonly=True, tracking=True,
    )

    entity_config_ids = fields.One2many(
        "tally.entity.config", "instance_id", string="Entities",
    )
    mapping_count = fields.Integer(compute="_compute_counts")
    log_count = fields.Integer(compute="_compute_counts")
    queue_pending = fields.Integer(compute="_compute_counts")

    _sql_constraints = [
        ("name_company_uniq", "unique(name, company_id)",
         "Instance name must be unique per company."),
    ]

    def _compute_counts(self):
        mapping = self.env["tally.mapping"]
        log = self.env["tally.sync.log"]
        queue = self.env["tally.sync.queue"]
        for rec in self:
            rec.mapping_count = mapping.search_count([("instance_id", "=", rec.id)])
            rec.log_count = log.search_count([("instance_id", "=", rec.id)])
            rec.queue_pending = queue.search_count(
                [("instance_id", "=", rec.id), ("state", "in", ("pending", "sent"))])

    # ------------------------------------------------------------------ actions
    def action_generate_token(self):
        for rec in self:
            rec.agent_token = secrets.token_urlsafe(32)
        return True

    def action_load_default_entities(self):
        """Seed the standard entity set (idempotent)."""
        self.ensure_one()
        existing = set(self.entity_config_ids.mapped("entity"))
        commands = []
        for entity, model, sot, seq in DEFAULT_ENTITIES:
            if entity in existing:
                continue
            commands.append((0, 0, {
                "entity": entity,
                "odoo_model_name": model,
                "source_of_truth": sot,
                "direction": direction_for_source(sot),
                "sequence": seq,
            }))
        if commands:
            self.write({"entity_config_ids": commands})
        return True

    def action_test_connection(self):
        self.ensure_one()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Agent-mediated connection"),
                "message": _(
                    "The live TCP test to Tally is performed by the on-prem Sync Agent. "
                    "Ensure the agent is installed near Tally, paired with this instance's "
                    "token, and that Tally's XML gateway is enabled on port %s.",
                    self.tally_port or 9000),
                "type": "info",
                "sticky": False,
            },
        }

    def action_view_mappings(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Mappings"),
            "res_model": "tally.mapping",
            "view_mode": "list,form",
            "domain": [("instance_id", "=", self.id)],
            "context": {"default_instance_id": self.id},
        }

    def action_view_logs(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Sync Logs"),
            "res_model": "tally.sync.log",
            "view_mode": "list,pivot,graph,form",
            "domain": [("instance_id", "=", self.id)],
        }

    def action_open_onboarding(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Tally Onboarding"),
            "res_model": "tally.onboarding",
            "view_mode": "form",
            "target": "new",
            "context": {"default_instance_id": self.id},
        }

    # ------------------------------------------------------------------ cron
    @api.model
    def _cron_health_check(self):
        """Flag instances offline when the agent heartbeat goes stale."""
        threshold = fields.Datetime.subtract(fields.Datetime.now(), minutes=5)
        stale = self.search([
            ("state", "=", "online"),
            ("agent_last_seen", "<", threshold),
        ])
        stale.write({"state": "offline"})
        return True
