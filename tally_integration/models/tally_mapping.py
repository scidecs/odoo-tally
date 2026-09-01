# -*- coding: utf-8 -*-
from odoo import fields, models
from .constants import ENTITY_SELECTION


class TallyMapping(models.Model):
    _name = "tally.mapping"
    _description = "Tally <-> Odoo Identity Map"
    _order = "write_date desc"

    instance_id = fields.Many2one(
        "tally.instance", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(
        related="instance_id.company_id", store=True, index=True)
    entity = fields.Selection(ENTITY_SELECTION, required=True, index=True)

    tally_guid = fields.Char(string="Tally GUID", index=True)
    tally_masterid = fields.Char(string="Tally Master/Alter ID")
    odoo_model_name = fields.Char(string="Odoo Model", index=True)
    odoo_res_id = fields.Integer(string="Odoo Record ID", index=True)

    content_hash = fields.Char(
        string="Content Hash",
        help="Hash of the last synced payload; used for echo/loop suppression.")
    last_origin = fields.Selection(
        [("tally", "Tally"), ("odoo", "Odoo")], string="Last Change Origin")
    last_sync = fields.Datetime()
    state = fields.Selection(
        [("active", "Active"), ("conflict", "Conflict"), ("error", "Error")],
        default="active", index=True)

    _guid_uniq = models.Constraint(
        "UNIQUE(instance_id, entity, tally_guid)",
        "This Tally GUID is already mapped for this entity.",
    )

    def action_open_odoo_record(self):
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
