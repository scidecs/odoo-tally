# -*- coding: utf-8 -*-
import hashlib
import uuid

from odoo import api, fields, models

from .constants import ENTITY_SELECTION
from .compat import config_param, sql_constraints

VOUCHER_ENTITIES = (
    "sales", "credit_note", "purchase", "debit_note", "receipt", "payment",
    "journal", "contra", "stock_journal",
)


class TallyMapping(models.Model):
    """One Odoo record <-> one Tally object.

    Tally identifies masters by *name* and assigns its own GUID/number to every
    imported voucher; the GUID we send is only kept as REMOTEALTGUID. So a
    mapping carries both sides of the identity:

    * ``remote_id`` - the GUID Odoo sends (Tally's REMOTEALTGUID), stable forever
    * ``tally_guid`` / ``tally_masterid`` - Tally's own identity, bound after push
      or taken from the inbound record
    * ``tally_alterid`` - the Tally revision already reflected in Odoo; an inbound
      record at or below it is an echo and is skipped
    * ``tally_name`` / ``tally_voucher_*`` - how Tally addresses the object for
      renames, alterations and cancellations
    """
    _name = "tally.mapping"
    _description = "Tally <-> Odoo Identity Map"
    _order = "write_date desc"

    instance_id = fields.Many2one(
        "tally.instance", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(
        related="instance_id.company_id", store=True, index=True)
    entity = fields.Selection(ENTITY_SELECTION, required=True, index=True)

    tally_guid = fields.Char(string="Tally GUID", index=True)
    remote_id = fields.Char(
        string="Odoo Remote ID", index=True, copy=False,
        help="GUID sent by Odoo; Tally stores it as REMOTEALTGUID.")
    tally_masterid = fields.Char(string="Tally MasterID")
    tally_alterid = fields.Integer(
        string="Tally AlterID", help="Tally revision already reflected in Odoo.")
    tally_name = fields.Char(string="Name in Tally", index=True)
    tally_voucher_type = fields.Char(string="Tally Voucher Type")
    tally_voucher_number = fields.Char(string="Tally Voucher Number", index=True)
    tally_voucher_date = fields.Date(string="Tally Voucher Date")
    odoo_model_name = fields.Char(string="Odoo Model", index=True)
    odoo_res_id = fields.Integer(string="Odoo Record ID", index=True)

    odoo_fingerprint = fields.Char(
        help="Accounting content of the Odoo document when it was last synchronised; a "
             "Tally document is only written back when this changes.")
    content_hash = fields.Char(
        string="Content Hash",
        help="Hash of the last payload pushed to Tally; identical re-pushes are skipped.")
    last_origin = fields.Selection(
        [("tally", "Tally"), ("odoo", "Odoo")], string="Created In")
    last_sync = fields.Datetime()
    state = fields.Selection(
        [("active", "Active"), ("conflict", "Conflict"), ("error", "Error"), ("orphan", "Orphan (Deleted in Tally)")],
        default="active", index=True)
    is_orphan = fields.Boolean(
        string="Deleted in Tally", default=False, index=True,
        help="Flagged when this record is no longer found in Tally during reconciliation.")
    orphan_date = fields.Datetime(string="Marked Orphan Date")
    is_bound = fields.Boolean(compute="_compute_is_bound", string="Bound to Tally")

    sql_constraints(
        locals(),
        ("guid_uniq", "UNIQUE(instance_id, entity, tally_guid)",
         "This Tally GUID is already mapped for this entity."),
        ("odoo_record_uniq", "UNIQUE(instance_id, entity, odoo_model_name, odoo_res_id)",
         "This Odoo record is already mapped for this entity."),
    )

    @api.depends("tally_guid")
    def _compute_is_bound(self):
        for rec in self:
            rec.is_bound = bool(rec.tally_guid)

    # ------------------------------------------------------------------ lookup
    @api.model
    def for_record(self, instance, entity, model_name, res_id):
        return self.search([
            ("instance_id", "=", instance.id), ("entity", "=", entity),
            ("odoo_model_name", "=", model_name), ("odoo_res_id", "=", res_id),
        ], limit=1)

    @api.model
    def find_inbound(self, instance, entity, record):
        """Resolve the mapping for a record read from Tally.

        1. Tally's own GUID (records already linked).
        2. REMOTEALTGUID == our remote id (Odoo-created, even if never bound).
        3. For masters awaiting binding, the name Odoo pushed.
        """
        family = VOUCHER_ENTITIES if entity in VOUCHER_ENTITIES else (entity,)
        base = [("instance_id", "=", instance.id), ("entity", "in", family)]
        guid = (record.get("guid") or "").strip()
        if guid:
            found = self.search(base + [("tally_guid", "=", guid)], limit=1)
            if found:
                return found
        remote = (record.get("remote_alt_guid") or "").strip()
        if remote:
            found = self.search(base + [("remote_id", "=", remote)], limit=1)
            if found:
                return found
        name = (record.get("name") or "").strip()
        if name and entity not in VOUCHER_ENTITIES:
            found = self.search(base + [
                ("tally_guid", "=", False), ("tally_name", "=", name)], limit=1)
            if found:
                return found
        return self.browse()

    # ---------------------------------------------------------------- outbound
    @api.model
    def outbound_guid(self, instance, entity, model_name, res_id):
        """Stable GUID Odoo sends for a record (kept by Tally as REMOTEALTGUID)."""
        existing = self.for_record(instance, entity, model_name, res_id)
        if existing.remote_id:
            return existing.remote_id
        db_uuid = config_param(self.env, "database.uuid") or self.env.cr.dbname
        seed = "%s:%s:%s:%s:%s" % (db_uuid, instance.id, entity, model_name, res_id)
        return str(uuid.uuid5(uuid.NAMESPACE_URL, seed))

    @api.model
    def outbound_address(self, instance, entity, model_name, res_id):
        """How Tally currently knows this record: ``{name, voucher_type,
        voucher_number, voucher_date}`` (empty until bound)."""
        m = self.for_record(instance, entity, model_name, res_id)
        return {
            "name": m.tally_name if m.tally_guid else False,
            "voucher_type": m.tally_voucher_type,
            "voucher_number": m.tally_voucher_number if m.tally_guid else False,
            "voucher_date": m.tally_voucher_date,
            "bound": bool(m.tally_guid),
            "origin": m.last_origin,
        }

    @api.model
    def register_outbound(self, instance, entity, model_name, res_id, payload_xml,
                          guid=None, allow_tally_origin=False, tally_name=None, fingerprint=None):
        """Record an outbound push and decide whether it must be queued.

        Returns False for an identical re-push, or when a record owned by Tally
        must not be written back (entity source of truth ``tally``/``tally_master``,
        or a Tally voucher whose policy does not accept Odoo edits).
        """
        p_hash = hashlib.sha256(payload_xml.encode("utf-8")).hexdigest()
        mapping = self.for_record(instance, entity, model_name, res_id)
        cfg = instance.entity_config_ids.filtered(lambda c: c.entity == entity)[:1]
        sot = cfg.source_of_truth if cfg else "tally"
        if mapping:
            if mapping.content_hash == p_hash:
                return False
            if mapping.last_origin == "tally":
                if sot in ("tally", "tally_master"):
                    return False
                if not allow_tally_origin and sot not in ("odoo", "bidirectional"):
                    return False
                if fingerprint and mapping.odoo_fingerprint == fingerprint:
                    # Posted/reconciled/re-saved but not edited: nothing to write back.
                    return False
            vals = {
                "content_hash": p_hash,
                "remote_id": mapping.remote_id or guid,
                "last_sync": fields.Datetime.now(),
                "state": "active",
            }
            if tally_name and not mapping.tally_guid:
                vals["tally_name"] = tally_name
            if fingerprint:
                vals["odoo_fingerprint"] = fingerprint
            mapping.write(vals)
            return True
        self.create({
            "instance_id": instance.id,
            "entity": entity,
            "remote_id": guid or self.outbound_guid(instance, entity, model_name, res_id),
            "tally_name": tally_name,
            "odoo_model_name": model_name,
            "odoo_res_id": res_id,
            "content_hash": p_hash,
            "odoo_fingerprint": fingerprint,
            "last_origin": "odoo",
            "last_sync": fields.Datetime.now(),
            "state": "active",
        })
        return True

    def bind_identity(self, identity):
        """Store Tally's identity for a pushed record.

        ``identity`` is a parsed Tally object (guid, alterid, master_id, name,
        voucher_type, voucher_number, date).
        """
        for mapping in self:
            guid = identity.get("guid")
            if not guid:
                continue
            clash = self.search([
                ("instance_id", "=", mapping.instance_id.id), ("entity", "=", mapping.entity),
                ("tally_guid", "=", guid), ("id", "!=", mapping.id)], limit=1)
            if clash:
                # The same Tally object was already linked to another Odoo record
                # (e.g. a name-matched master). Keep the older link, flag this one.
                mapping.write({"state": "conflict"})
                continue
            vals = {
                "tally_guid": guid,
                "tally_masterid": identity.get("master_id") or mapping.tally_masterid,
                "tally_alterid": max(int(identity.get("alterid") or 0), mapping.tally_alterid or 0),
                "last_sync": fields.Datetime.now(),
                "state": "active",
                "is_orphan": False,
            }
            if identity.get("name"):
                vals["tally_name"] = identity["name"]
            if identity.get("voucher_number"):
                vals.update({
                    "tally_voucher_number": identity["voucher_number"],
                    "tally_voucher_type": identity.get("voucher_type") or mapping.tally_voucher_type,
                    "tally_voucher_date": identity.get("date") or mapping.tally_voucher_date,
                })
            mapping.write(vals)
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
