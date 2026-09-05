# -*- coding: utf-8 -*-
"""Durable quarantine for malformed inbound Tally records."""
import hashlib
import json

from odoo import api, fields, models, _

from .constants import ENTITY_SELECTION


class TallyInboundDeadLetter(models.Model):
    _name = "tally.inbound.dead.letter"
    _description = "Tally Inbound Quarantine"
    _order = "last_failed desc, id desc"

    instance_id = fields.Many2one(
        "tally.instance", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(
        related="instance_id.company_id", store=True, index=True)
    entity = fields.Selection(ENTITY_SELECTION, required=True, index=True)
    record_key = fields.Char(required=True, index=True)
    record_name = fields.Char(index=True)
    tally_guid = fields.Char(index=True)
    tally_alterid = fields.Integer(index=True)
    payload_hash = fields.Char(required=True, index=True)
    payload = fields.Text(required=True)
    error = fields.Text(required=True)
    attempts = fields.Integer(default=1, required=True)
    state = fields.Selection([
        ("pending", "Retrying"),
        ("quarantined", "Quarantined"),
        ("resolved", "Resolved"),
    ], default="pending", required=True, index=True)
    first_failed = fields.Datetime(default=fields.Datetime.now, required=True)
    last_failed = fields.Datetime(default=fields.Datetime.now, required=True)
    resolved_date = fields.Datetime()

    _record_revision_uniq = models.Constraint(
        "UNIQUE(instance_id, entity, record_key, tally_alterid)",
        "This inbound Tally record revision is already tracked.",
    )

    @api.model
    def _identity(self, entity, record):
        guid = str(record.get("guid") or "").strip()
        name = str(record.get("voucher_number") or record.get("name") or "").strip()
        alterid = int(record.get("alterid") or 0)
        if guid:
            return guid, guid, name, alterid
        stable = "%s:%s" % (entity, name or "anonymous")
        return stable, False, name, alterid

    @api.model
    def for_record(self, instance, entity, record):
        key, _guid, _name, alterid = self._identity(entity, record)
        return self.search([
            ("instance_id", "=", instance.id), ("entity", "=", entity),
            ("record_key", "=", key), ("tally_alterid", "=", alterid),
        ], limit=1)

    @api.model
    def record_failure(self, instance, entity, record, error):
        key, guid, name, alterid = self._identity(entity, record)
        payload = json.dumps(record, sort_keys=True, default=str, ensure_ascii=False)
        payload_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        dead = self.for_record(instance, entity, record)
        attempts = (dead.attempts if dead else 0) + 1
        threshold = max(int(instance.inbound_quarantine_threshold or 3), 1)
        vals = {
            "record_name": name, "tally_guid": guid, "payload_hash": payload_hash,
            "payload": payload, "error": str(error), "attempts": attempts,
            "last_failed": fields.Datetime.now(),
            "state": "quarantined" if attempts >= threshold else "pending",
        }
        if dead:
            dead.write(vals)
        else:
            dead = self.create(dict(vals, instance_id=instance.id, entity=entity,
                                    record_key=key, tally_alterid=alterid))
        return dead

    @api.model
    def resolve_record(self, instance, entity, record):
        key, _guid, _name, _alterid = self._identity(entity, record)
        dead = self.search([
            ("instance_id", "=", instance.id), ("entity", "=", entity),
            ("record_key", "=", key), ("state", "!=", "resolved"),
        ])
        if dead:
            dead.write({"state": "resolved", "resolved_date": fields.Datetime.now()})

    def action_retry(self):
        for dead in self:
            cfg = dead.instance_id.entity_config_ids.filtered(
                lambda c: c.entity == dead.entity)[:1]
            if cfg and dead.tally_alterid and cfg.last_alterid >= dead.tally_alterid:
                cfg.write({"last_alterid": max(dead.tally_alterid - 1, 0)})
            dead.write({"state": "pending", "attempts": 0,
                        "resolved_date": False})
        return {
            "type": "ir.actions.client", "tag": "display_notification",
            "params": {"title": _("Retry scheduled"),
                       "message": _("The entity watermark was rewound for the next pull."),
                       "type": "success", "sticky": False},
        }

    def action_quarantine(self):
        self.write({"state": "quarantined"})

    def action_resolve(self):
        self.write({"state": "resolved", "resolved_date": fields.Datetime.now()})

