# -*- coding: utf-8 -*-
"""HTTP endpoints consumed by the on-prem Sync Agent.

All routes are token-authenticated via the ``X-Tally-Token`` header, which the
agent obtains when it is paired with a ``tally.instance``. The agent makes
outbound-only HTTPS to these endpoints, so no inbound ports are opened on-site.

The agent is a relay: Odoo builds every Tally request (structure, masters,
vouchers, identity read-back) and processes every raw Tally response, so the
sync rules are identical to direct mode and never depend on the agent version.
"""
import json

from odoo import fields, http
from odoo.http import request

from ..models.compat import ODOO_MAJOR
from ..services import tally_xml_parser
from ..services.sync_engine import SyncEngine

# ``type='json'`` is a deprecated alias of ``jsonrpc`` since Odoo 19.
JSON_ROUTE = "jsonrpc" if ODOO_MAJOR >= 19 else "json"
MAX_RESPONSE_BYTES = 200 * 1024 * 1024


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

    @http.route("/tally/agent/heartbeat", type=JSON_ROUTE, auth="public",
                methods=["POST"], csrf=False)
    def heartbeat(self, **kw):
        instance = self._authenticate()
        if not instance:
            return {"error": "unauthorized"}
        instance.write({"agent_last_seen": fields.Datetime.now(), "state": "online"})
        due = (not instance.last_pull) or (
            (fields.Datetime.now() - instance.last_pull).total_seconds()
            >= (instance.pull_interval or 15) * 60)
        return {
            "ok": True,
            "poll_interval": instance.poll_interval,
            "tally_company": instance.tally_company,
            "pull_due": bool(due),
            "structure_requests": instance._structure_requests() if due else {},
            "pull_plan": [[key, xml] for key, xml in instance._pull_plan()] if due else [],
        }

    @http.route("/tally/agent/companies", type=JSON_ROUTE, auth="public",
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

    @http.route("/tally/agent/pull", type=JSON_ROUTE, auth="public",
                methods=["POST"], csrf=False)
    def pull(self, limit=50, **kw):
        """Agent pulls pending outbound (Odoo -> Tally) work, masters first."""
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
        items = Queue.search([
            ("instance_id", "=", instance.id), "|", ("state", "=", "pending"),
            "&", ("state", "=", "failed"), ("attempts", "<", instance.MAX_QUEUE_ATTEMPTS),
        ], order="create_date, id")
        order = {e: n for n, e in enumerate(instance.MASTER_PUSH_ORDER)}
        items = items.sorted(lambda i: (
            1 if "<VOUCHER" in (i.payload or "") else 0, order.get(i.entity, 99), i.id))[:limit]
        items.write({"state": "sent", "sent_at": fields.Datetime.now()})
        result = []
        for item in items:
            verify_xml, expected = instance._voucher_address_check(item)
            result.append({
                "id": item.id,
                "entity": item.entity,
                "idempotency_key": item.idempotency_key,
                "payload": item.payload,
                "is_voucher": "<VOUCHER" in (item.payload or ""),
                # Agent must run this and send only if it returns exactly expected_guid.
                "verify_request": verify_xml or False,
                "expected_guid": expected or False,
            })
        return {"items": result}

    @http.route("/tally/agent/identity", type=JSON_ROUTE, auth="public",
                methods=["POST"], csrf=False)
    def identity(self, item_id=None, last_vch_id=None, **kw):
        """Identity read-back request for an item the agent just imported."""
        instance = self._authenticate()
        if not instance:
            return {"error": "unauthorized"}
        item = request.env["tally.sync.queue"].sudo().browse(int(item_id or 0)).exists()
        if not item or item.instance_id != instance:
            return {"error": "unknown_item"}
        for coll, pairs in instance._identity_pairs(item).items():
            return {"collection": coll, "request": instance._identity_request(coll, pairs, last_vch_id)}
        return {"collection": False, "request": False}

    @http.route("/tally/agent/push", type=JSON_ROUTE, auth="public",
                methods=["POST"], csrf=False)
    def push(self, entity=None, alterid=None, records=None, xml_payload=None,
             structure=None, steps=None, **kw):
        """Agent relays Tally export responses.

        Current agents send ``structure`` (request key -> raw XML) and ordered
        ``steps`` ([key, raw XML]) produced from the heartbeat's pull plan.
        """
        instance = self._authenticate()
        if not instance:
            return {"error": "unauthorized"}
        if structure is not None:
            size = sum(len(v or "") for v in structure.values()) + sum(len(r or "") for _k, r in (steps or []))
            if size > MAX_RESPONSE_BYTES:
                return {"error": "payload_too_large"}
            groups, ledgers, tree = instance._apply_tally_structure(structure)
            engine = SyncEngine(request.env, instance)
            processed, failed = 0, []
            for key, raw in (steps or []):
                try:
                    processed += instance._process_pull_step(engine, key, raw, groups, ledgers, tree)
                except Exception as e:
                    failed.append(key)
                    request.env["tally.sync.log"].sudo().log(
                        instance, "tally_to_odoo", key if key != "vouchers" else "journal", "error",
                        "Pull failed for %s: %s" % (key, e))
            instance.last_pull = fields.Datetime.now()
            return {"ok": True, "processed": processed, "failed": failed}

        # Legacy single-entity push (older agents).
        if xml_payload and not records:
            root = tally_xml_parser.parse_tally_xml_root(xml_payload)
            if root is not None:
                parsers = {
                    "group": tally_xml_parser.parse_groups_from_xml,
                    "uom": tally_xml_parser.parse_units_from_xml,
                    "stock_group": tally_xml_parser.parse_stock_groups_from_xml,
                    "stock_item": tally_xml_parser.parse_stock_items_from_xml,
                    "cost_centre": tally_xml_parser.parse_cost_centres_from_xml,
                    "godown": tally_xml_parser.parse_godowns_from_xml,
                    "currency": tally_xml_parser.parse_currencies_from_xml,
                }
                if entity in instance.LEDGER_ENTITIES:
                    tree = json.loads(instance.tally_group_tree or "{}") or None
                    records = tally_xml_parser.filter_ledgers_for_entity(
                        tally_xml_parser.parse_ledgers_from_xml(root), entity, tree)
                elif entity in parsers:
                    records = parsers[entity](root)
                elif entity == "vouchers" or entity in instance.PULL_VOUCHER_ENTITIES:
                    records = tally_xml_parser.parse_vouchers_from_xml(root)
                    entity = "vouchers"
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

    @http.route("/tally/agent/ack", type=JSON_ROUTE, auth="public",
                methods=["POST"], csrf=False)
    def ack(self, results=None, **kw):
        """Agent acknowledges outbound items it wrote into Tally.

        Each result may carry ``identity_response`` (raw XML of the identity
        read-back) so Odoo binds Tally's GUID/number exactly as in direct mode.
        """
        instance = self._authenticate()
        if not instance:
            return {"error": "unauthorized"}
        Queue = request.env["tally.sync.queue"].sudo()
        for res in (results or []):
            item = Queue.browse(int(res.get("id") or 0)).exists()
            if not item or item.instance_id != instance:
                continue
            if res.get("ok"):
                item.write({"state": "acked", "sent_at": False, "attempts": item.attempts + 1,
                            "error": False})
                if res.get("identity_response"):
                    for coll, pairs in instance._identity_pairs(item).items():
                        instance._apply_identity_response(
                            coll, pairs, res["identity_response"], res.get("last_vch_id"))
            else:
                item.write({
                    "state": "failed",
                    "sent_at": False,
                    "attempts": item.attempts + 1,
                    "error": res.get("error"),
                })
        return {"ok": True}
