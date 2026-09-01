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

    @api.model
    def register_outbound(self, instance, entity, model_name, res_id, payload_xml, guid=None):
        """Register or check outbound record for echo and re-push suppression.

        Returns:
            bool: True if record should be enqueued to Tally, False if skipped (echo/re-push).
        """
        import hashlib
        p_hash = hashlib.sha256(payload_xml.encode("utf-8")).hexdigest()
        mapping = self.search([
            ("instance_id", "=", instance.id),
            ("odoo_model_name", "=", model_name),
            ("odoo_res_id", "=", res_id),
        ], limit=1)

        if mapping:
            # If origin was Tally and content has not changed (e.g. manual post of imported voucher), skip re-pushing!
            if mapping.last_origin == "tally" and mapping.content_hash == p_hash:
                return False
            mapping.write({
                "last_origin": "odoo",
                "content_hash": p_hash,
                "last_sync": fields.Datetime.now(),
                "state": "active",
            })
            return True
        else:
            self.create({
                "instance_id": instance.id,
                "entity": entity,
                "tally_guid": guid or f"odoo_{entity}_{res_id}",
                "odoo_model_name": model_name,
                "odoo_res_id": res_id,
                "content_hash": p_hash,
                "last_origin": "odoo",
                "last_sync": fields.Datetime.now(),
                "state": "active",
            })
            return True

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
