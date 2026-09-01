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
        return request.env["tally.instance"].sudo().search(
            [("agent_token", "=", token)], limit=1) or None

    @http.route("/tally/agent/heartbeat", type="json", auth="public",
                methods=["POST"], csrf=False)
    def heartbeat(self, **kw):
        instance = self._authenticate()
        if not instance:
            return {"error": "unauthorized"}
        instance.write({"agent_last_seen": fields.Datetime.now(), "state": "online"})
        return {"ok": True, "poll_interval": instance.poll_interval}

    @http.route("/tally/agent/companies", type="json", auth="public",
                methods=["POST"], csrf=False)
    def companies(self, companies=None, **kw):
        """Agent reports the Tally company files it can currently see."""
        instance = self._authenticate()
        if not instance:
            return {"error": "unauthorized"}
        Disc = request.env["tally.discovered.company"].sudo()
        now = fields.Datetime.now()
        for name in (companies or []):
            rec = Disc.search([("name", "=", name)], limit=1)
            if rec:
                rec.last_seen = now
            else:
                Disc.create({"name": name, "last_seen": now})
        return {"ok": True, "count": len(companies or [])}

    @http.route("/tally/agent/pull", type="json", auth="public",
                methods=["POST"], csrf=False)
    def pull(self, limit=50, **kw):
        """Agent pulls pending outbound (Odoo -> Tally) work."""
        instance = self._authenticate()
        if not instance:
            return {"error": "unauthorized"}
        items = request.env["tally.sync.queue"].sudo().search(
            [("instance_id", "=", instance.id), ("state", "=", "pending")],
            limit=int(limit), order="create_date")
        items.write({"state": "sent"})
        return {"items": [{
            "id": item.id,
            "entity": item.entity,
            "idempotency_key": item.idempotency_key,
            "payload": item.payload,
        } for item in items]}

    @http.route("/tally/agent/push", type="json", auth="public",
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
                elif entity == "stock_item":
                    records = tally_xml_parser.parse_stock_items_from_xml(root)
                elif entity == "cost_centre":
                    records = tally_xml_parser.parse_cost_centres_from_xml(root)
                elif entity == "godown":
                    records = tally_xml_parser.parse_godowns_from_xml(root)
                elif entity in ("sales", "purchase", "receipt", "payment", "journal", "contra", "credit_note", "debit_note"):
                    records = tally_xml_parser.parse_vouchers_from_xml(root)

        if not records:
            return {"ok": True, "received": 0, "message": "No records found in payload"}

        engine = SyncEngine(request.env, instance)
        result = engine.process_inbound_batch(entity=entity, records=records, alterid=alterid)

        return {
            "ok": True,
            "received": len(records),
            "processed": result.get("processed", 0),
            "errors": result.get("errors", 0),
            "watermark": result.get("watermark", 0),
        }

    @http.route("/tally/agent/ack", type="json", auth="public",
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
                item.write({"state": "acked", "attempts": item.attempts + 1})
            else:
                item.write({
                    "state": "failed",
                    "attempts": item.attempts + 1,
                    "error": res.get("error"),
                })
        return {"ok": True}
