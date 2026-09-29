# -*- coding: utf-8 -*-
import json

from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestTallyAgentHttp(HttpCase):
    """Exercise the cloud-Odoo/on-prem-agent boundary over real HTTP."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["tally.instance"].search([
            ("company_id", "=", cls.env.company.id), ("active", "=", True),
        ]).write({"active": False})
        cls.token = "odoo18-agent-http-test-token"
        cls.instance = cls.env["tally.instance"].create({
            "name": "Odoo 18 HTTP Agent Test",
            "company_id": cls.env.company.id,
            "tally_company": "Odoo 18 Test Company",
            "connection_mode": "agent",
            "agent_token": cls.token,
            "auto_post": False,
            "direct_auto_pull": False,
        })
        cls.config = cls.env["tally.entity.config"].create({
            "instance_id": cls.instance.id,
            "entity": "uom",
            "direction": "both",
            "source_of_truth": "bidirectional",
            "enabled": True,
        })

    def _post(self, path, params=None, token=None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-Tally-Token"] = token
        response = self.url_open(
            path,
            data=json.dumps({"params": params or {}}),
            headers=headers,
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertNotIn("error", payload)
        return payload["result"]

    def test_agent_http_roundtrip(self):
        unauthorized = self._post("/tally/agent/heartbeat")
        self.assertEqual(unauthorized, {"error": "unauthorized"})

        heartbeat = self._post(
            "/tally/agent/heartbeat", token=self.token)
        self.assertTrue(heartbeat["ok"])
        self.assertEqual(heartbeat["tally_company"], "Odoo 18 Test Company")
        self.assertTrue(heartbeat["pull_due"])
        self.assertIn("groups", heartbeat["structure_requests"])
        self.assertEqual([step[0] for step in heartbeat["pull_plan"]], ["uom"])
        self.assertIn("RemoteAltGUID", heartbeat["pull_plan"][0][1])

        relayed = self._post("/tally/agent/push", {
            "structure": {
                "groups": "<ENVELOPE><GROUP NAME=\"Sundry Debtors\"><PARENT/></GROUP></ENVELOPE>",
                "ledgers": "<ENVELOPE></ENVELOPE>",
            },
            "steps": [["uom", """<ENVELOPE><UNIT NAME="Relay Crates">
                  <GUID>99999999-9999-9999-9999-999999999999</GUID>
                  <ALTERID>12</ALTERID><DECIMALPLACES>0</DECIMALPLACES></UNIT></ENVELOPE>"""]],
        }, token=self.token)
        self.assertEqual(relayed["processed"], 1)
        self.assertEqual(relayed["failed"], [])
        self.assertTrue(self.instance.last_pull)

        discovered = self._post(
            "/tally/agent/companies",
            {"companies": ["Odoo 18 Test Company"]},
            token=self.token,
        )
        self.assertEqual(discovered["count"], 1)
        self.assertTrue(self.env["tally.discovered.company"].search([
            ("reporter_instance_id", "=", self.instance.id),
            ("name", "=", "Odoo 18 Test Company"),
        ]))

        inbound = self._post(
            "/tally/agent/push",
            {"entity": "uom", "xml_payload": """
                <ENVELOPE><UNIT NAME="Agent Boxes">
                  <GUID>88888888-8888-8888-8888-888888888888</GUID>
                  <ALTERID>18</ALTERID><DECIMALPLACES>2</DECIMALPLACES>
                </UNIT></ENVELOPE>
            """},
            token=self.token,
        )
        self.assertEqual(inbound["processed"], 1)
        self.assertEqual(inbound["errors"], 0)
        self.assertEqual(inbound["watermark"], 18)
        self.assertTrue(self.env["uom.uom"].search([
            ("name", "=ilike", "Agent Boxes"),
        ]))

        queue = self.env["tally.sync.queue"].create({
            "instance_id": self.instance.id,
            "entity": "uom",
            "idempotency_key": "odoo18-http-queue",
            "payload": "<ENVELOPE><TALLYMESSAGE/></ENVELOPE>",
        })
        pulled = self._post(
            "/tally/agent/pull", {"limit": 20}, token=self.token)
        self.assertEqual([item["id"] for item in pulled["items"]], [queue.id])
        self.assertEqual(queue.state, "sent")

        acknowledged = self._post(
            "/tally/agent/ack",
            {"results": [{"id": queue.id, "ok": True}]},
            token=self.token,
        )
        self.assertTrue(acknowledged["ok"])
        self.assertEqual(queue.state, "acked")
        self.assertEqual(queue.attempts, 1)
