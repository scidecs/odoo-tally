# -*- coding: utf-8 -*-
"""HTTP endpoints consumed by the on-prem Sync Agent.

All routes are token-authenticated via the ``X-Tally-Token`` header, which the
agent obtains when it is paired with a ``tally.instance``. The agent makes
outbound-only HTTPS to these endpoints, so no inbound ports are opened on-site.
"""
from odoo import fields, http
from odoo.http import request
from ..services.sync_engine import SyncEngine
from ..services import tally_xml_parser


class TallyAgentController(http.Controller):

    def _authenticate(self):
        """Return the paired instance for the request token, or None."""
        token = request.httprequest.headers.get("X-Tally-Token")
        if not token:
            return None
        instance = request.env["tally.instance"].sudo().search(
            [("agent_token", "=", token)], limit=1)
        if not instance:
            return None
        instance._guard_environment()
        return instance if instance.active else None

    @http.route("/tally/agent/heartbeat", type="jsonrpc", auth="public",
                methods=["POST"], csrf=False)
    def heartbeat(self, **kw):
        instance = self._authenticate()
        if not instance:
            return {"error": "unauthorized"}
        instance.write({"agent_last_seen": fields.Datetime.now(), "state": "online"})
        inbound = instance.entity_config_ids.filtered(
            lambda c: c.enabled and c.direction in ("tally_to_odoo", "both"))
        return {
            "ok": True,
            "poll_interval": instance.poll_interval,
            "tally_company": instance.tally_company,
            "entities": [{"entity": c.entity, "last_alterid": c.last_alterid} for c in inbound],
        }

    @http.route("/tally/agent/companies", type="jsonrpc", auth="public",
                methods=["POST"], csrf=False)
    def companies(self, companies=None, **kw):
        """Agent reports the Tally company files it can currently see."""
        instance = self._authenticate()
        if not instance:
            return {"error": "unauthorized"}
        Disc = request.env["tally.discovered.company"].sudo()
        now = fields.Datetime.now()
        clean_names = [str(name).strip()[:255] for name in (companies or [])[:200] if str(name).strip()]
        for name in clean_names:
            rec = Disc.search([
                ("reporter_instance_id", "=", instance.id), ("name", "=", name),
            ], limit=1)
            if rec:
                rec.last_seen = now
            else:
                Disc.create({
                    "name": name, "reporter_instance_id": instance.id, "last_seen": now,
                })
        return {"ok": True, "count": len(clean_names)}

    @http.route("/tally/agent/pull", type="jsonrpc", auth="public",
                methods=["POST"], csrf=False)
    def pull(self, limit=50, **kw):
        """Agent pulls pending outbound (Odoo -> Tally) work."""
        instance = self._authenticate()
        if not instance:
            return {"error": "unauthorized"}
        Queue = request.env["tally.sync.queue"].sudo()
        # Recover work leased by an agent that crashed before acknowledging it.
        lease_cutoff = fields.Datetime.subtract(fields.Datetime.now(), minutes=10)
        Queue.search([
            ("instance_id", "=", instance.id),
            ("state", "=", "sent"),
            "|", ("sent_at", "=", False), ("sent_at", "<", lease_cutoff),
        ]).write({"state": "pending", "sent_at": False})
        limit = min(max(int(limit), 1), 200)
        items = Queue.search(
            [("instance_id", "=", instance.id), ("state", "=", "pending")],
            limit=limit, order="create_date")
        items.write({"state": "sent", "sent_at": fields.Datetime.now()})
        return {"items": [{
            "id": item.id,
            "entity": item.entity,
            "idempotency_key": item.idempotency_key,
            "payload": item.payload,
        } for item in items]}

    @http.route("/tally/agent/push", type="jsonrpc", auth="public",
                methods=["POST"], csrf=False)
    def push(self, entity=None, alterid=None, records=None, xml_payload=None, **kw):
        """Agent pushes Tally -> Odoo deltas (as structured records or raw XML)."""
        instance = self._authenticate()
        if not instance:
            return {"error": "unauthorized"}

        # If raw XML payload was sent instead of pre-parsed records
        if xml_payload and not records:
            root = tally_xml_parser.parse_tally_xml_root(xml_payload)
            if root is not None:
                if entity == "group":
                    records = tally_xml_parser.parse_groups_from_xml(root)
                elif entity in ("ledger", "account_ledger"):
                    records = tally_xml_parser.parse_ledgers_from_xml(root)
                elif entity == "uom":
                    records = tally_xml_parser.parse_units_from_xml(root)
                elif entity == "stock_group":
                    records = tally_xml_parser.parse_stock_groups_from_xml(root)
                elif entity == "stock_item":
                    records = tally_xml_parser.parse_stock_items_from_xml(root)
                elif entity == "cost_centre":
                    records = tally_xml_parser.parse_cost_centres_from_xml(root)
                elif entity == "godown":
                    records = tally_xml_parser.parse_godowns_from_xml(root)
                elif entity == "currency":
                    records = tally_xml_parser.parse_currencies_from_xml(root)
                elif entity in ("tax", "opening_balance"):
                    records = tally_xml_parser.parse_ledgers_from_xml(root)
                elif entity in ("vouchers", "sales", "purchase", "receipt", "payment", "journal", "contra", "credit_note", "debit_note", "stock_journal"):
                    records = tally_xml_parser.parse_vouchers_from_xml(root)

                if entity in ("ledger", "account_ledger", "tax", "opening_balance"):
                    records = tally_xml_parser.filter_ledgers_for_entity(records, entity)

        if not records:
            return {"ok": True, "received": 0, "message": "No records found in payload"}
        if len(records) > 5000:
            return {"error": "batch_too_large", "maximum": 5000}

        engine = SyncEngine(request.env, instance)
        if entity == "vouchers":
            grouped = engine.process_vouchers(records, alterid=alterid)
            result = {
                "processed": sum((r or {}).get("processed", 0) for r in grouped.values()),
                "errors": sum((r or {}).get("errors", 0) for r in grouped.values()),
                "watermark": max([(r or {}).get("watermark", 0) for r in grouped.values()] or [0]),
            }
        else:
            result = engine.process_inbound_batch(entity=entity, records=records, alterid=alterid)

        return {
            "ok": True,
            "received": len(records),
            "processed": result.get("processed", 0),
            "errors": result.get("errors", 0),
            "watermark": result.get("watermark", 0),
        }

    @http.route("/tally/agent/ack", type="jsonrpc", auth="public",
                methods=["POST"], csrf=False)
    def ack(self, results=None, **kw):
        """Agent acknowledges outbound items it wrote into Tally."""
        instance = self._authenticate()
        if not instance:
            return {"error": "unauthorized"}
        Queue = request.env["tally.sync.queue"].sudo()
        for res in (results or []):
            item = Queue.browse(res.get("id")).exists()
            if not item or item.instance_id != instance:
                continue
            if res.get("ok"):
                item.write({"state": "acked", "sent_at": False, "attempts": item.attempts + 1})
            else:
                item.write({
                    "state": "failed",
                    "sent_at": False,
                    "attempts": item.attempts + 1,
                    "error": res.get("error"),
                })
        return {"ok": True}
