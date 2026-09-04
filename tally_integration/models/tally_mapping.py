# -*- coding: utf-8 -*-
from odoo import api, fields, models
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
        [("active", "Active"), ("conflict", "Conflict"), ("error", "Error"), ("orphan", "Orphan (Deleted in Tally)")],
        default="active", index=True)
    is_orphan = fields.Boolean(
        string="Deleted in Tally", default=False, index=True,
        help="Flagged when this record is no longer found in Tally during reconciliation.")
    orphan_date = fields.Datetime(string="Marked Orphan Date")

    _guid_uniq = models.Constraint(
        "UNIQUE(instance_id, entity, tally_guid)",
        "This Tally GUID is already mapped for this entity.",
    )

    @api.model
    def outbound_guid(self, instance, entity, model_name, res_id):
        """Return a stable RFC-4122 GUID that Tally will echo on later exports."""
        import uuid
        existing = self.search([
            ("instance_id", "=", instance.id),
            ("entity", "=", entity),
            ("odoo_model_name", "=", model_name),
            ("odoo_res_id", "=", res_id),
        ], limit=1)
        # Keep a GUID supplied by Tally, but migrate the legacy synthetic
        # ``odoo_<entity>_<id>`` identity to a real GUID before the next push.
        if existing and existing.tally_guid and not existing.tally_guid.startswith("odoo_"):
            return existing.tally_guid
        db_uuid = self.env["ir.config_parameter"].sudo().get_param("database.uuid") or self.env.cr.dbname
        seed = "%s:%s:%s:%s:%s" % (db_uuid, instance.id, entity, model_name, res_id)
        return str(uuid.uuid5(uuid.NAMESPACE_URL, seed))

    @api.model
    def register_outbound(self, instance, entity, model_name, res_id, payload_xml,
                          guid=None, allow_tally_origin=False):
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
            cfg = instance.entity_config_ids.filtered(lambda c: c.entity == entity)[:1]
            if mapping.last_origin == "odoo" and mapping.content_hash == p_hash:
                return False
            if mapping.last_origin == "tally":
                # Posting an imported invoice/payment changes workflow state but not its
                # accounting payload. Never bounce that event back to Tally. Master write
                # hooks may explicitly allow a real Odoo edit when policy permits it.
                if not allow_tally_origin or (cfg and cfg.source_of_truth in ("tally", "tally_master")):
                    return False
            mapping.write({
                "tally_guid": guid or mapping.tally_guid,
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
                "tally_guid": guid or self.outbound_guid(instance, entity, model_name, res_id),
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

    def action_restore_active(self):
        """Manually un-orphan or resolve conflict for this mapping."""
        self.write({"state": "active", "is_orphan": False, "orphan_date": False})
        return True
