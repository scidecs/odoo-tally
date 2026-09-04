#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TallyPrime On-Premise Sync Agent.

A lightweight, standalone Python daemon that runs alongside TallyPrime on the
local machine/network.

Responsibilities:
1. Outbound-only HTTPS to Odoo controllers (/tally/agent/*) using X-Tally-Token.
2. Reports heartbeat and open Tally company files.
3. Polls Tally's XML Gateway (port 9000) for AlterID deltas and pushes them to Odoo.
4. Pulls outbound XML import envelopes from Odoo and posts them to Tally XML Gateway.
5. Acknowledges results back to Odoo queue.
"""
import argparse
import json
import logging
import os
import sys
import time
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE_ROOT = os.path.join(ROOT, "tally_integration")
if MODULE_ROOT not in sys.path:
    sys.path.insert(0, MODULE_ROOT)
from services import tally_transport, tally_xml_builder

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("TallySyncAgent")


class TallyAgent:
    def __init__(self, odoo_url, token, tally_host="127.0.0.1", tally_port=9000, poll_interval=60):
        self.odoo_url = odoo_url.rstrip("/")
        self.token = token
        self.tally_url = f"http://{tally_host}:{tally_port}"
        self.poll_interval = poll_interval
        self.running = True
        self.tally_company = None
        self.inbound_entities = []

    # -------------------------------------------------------------------------
    # ODOO HTTP CLIENT
    # -------------------------------------------------------------------------
    def _call_odoo(self, endpoint, payload=None):
        """Call Odoo JSON-RPC / JSON endpoint."""
        url = f"{self.odoo_url}{endpoint}"
        headers = {
            "Content-Type": "application/json",
            "X-Tally-Token": self.token,
        }
        body = json.dumps({"params": payload or {}}).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))
                if "error" in res_data:
                    logger.error(f"Odoo error response on {endpoint}: {res_data['error']}")
                    return None
                return res_data.get("result", {})
        except Exception as e:
            logger.error(f"Failed to communicate with Odoo at {url}: {e}")
            return None

    # -------------------------------------------------------------------------
    # TALLY HTTP CLIENT
    # -------------------------------------------------------------------------
    def _call_tally(self, xml_payload):
        """Send raw XML request to Tally XML Gateway."""
        req = urllib.request.Request(
            self.tally_url,
            data=xml_payload.encode("utf-8"),
            headers={"Content-Type": "text/xml;charset=utf-8"},
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except Exception as e:
            logger.error(f"Failed to communicate with Tally at {self.tally_url}: {e}")
            return None

    # -------------------------------------------------------------------------
    # AGENT ROUTINES
    # -------------------------------------------------------------------------
    def heartbeat(self):
        """Send heartbeat to Odoo."""
        res = self._call_odoo("/tally/agent/heartbeat")
        if res and res.get("ok"):
            if "poll_interval" in res:
                self.poll_interval = int(res["poll_interval"])
            self.tally_company = res.get("tally_company") or self.tally_company
            self.inbound_entities = res.get("entities") or []
            logger.info("Heartbeat acknowledged by Odoo")
            return True
        return False

    def discover_companies(self):
        """Query Tally for loaded companies and report to Odoo."""
        query_xml = """<ENVELOPE>
  <HEADER><TALLYREQUEST>Export Data</TALLYREQUEST></HEADER>
  <BODY>
    <EXPORTDATA>
      <REQUESTDESC>
        <REPORTNAME>List of Companies</REPORTNAME>
      </REQUESTDESC>
    </EXPORTDATA>
  </BODY>
</ENVELOPE>"""
        resp_xml = self._call_tally(query_xml)
        if not resp_xml:
            return

        companies = []
        try:
            root = ET.fromstring(resp_xml)
            for c in root.iter("COMPANY"):
                name = c.attrib.get("NAME") or (c.find("NAME").text if c.find("NAME") is not None else None)
                if name and name not in companies:
                    companies.append(name.strip())
        except Exception as e:
            logger.warning(f"Could not parse discovered companies XML: {e}")

        if companies:
            logger.info(f"Discovered Tally companies: {companies}")
            self._call_odoo("/tally/agent/companies", {"companies": companies})

    def poll_and_push_deltas(self):
        """Poll Tally for new/altered records and push to Odoo."""
        voucher_entities = {
            "sales", "credit_note", "purchase", "debit_note", "receipt",
            "payment", "journal", "contra", "stock_journal",
        }
        voucher_enabled = False
        for config in self.inbound_entities:
            entity = config.get("entity")
            if entity in voucher_entities:
                voucher_enabled = True
                continue
            collection = tally_xml_builder.COLLECTION_MAP.get(entity)
            if not collection:
                continue
            export_xml = tally_xml_builder.build_collection_export(
                collection,
                company_name=self.tally_company,
                from_alterid=config.get("last_alterid") or None,
            )
            tally_resp = self._call_tally(export_xml)
            if tally_resp and "<ENVELOPE" in tally_resp:
                self._call_odoo("/tally/agent/push", {
                    "entity": entity,
                    "xml_payload": tally_resp,
                })
        if voucher_enabled:
            from datetime import date, timedelta
            export_xml = tally_xml_builder.build_voucher_export(
                date.today() - timedelta(days=30), date.today(), self.tally_company)
            tally_resp = self._call_tally(export_xml)
            if tally_resp and "<ENVELOPE" in tally_resp:
                self._call_odoo("/tally/agent/push", {
                    "entity": "vouchers", "xml_payload": tally_resp,
                })

    def pull_and_write_outbound(self):
        """Pull pending outbound items from Odoo and import them into Tally."""
        res = self._call_odoo("/tally/agent/pull", {"limit": 20})
        if not res or not res.get("items"):
            return

        items = res["items"]
        logger.info(f"Pulled {len(items)} outbound items from Odoo")
        ack_results = []

        for item in items:
            q_id = item.get("id")
            payload = item.get("payload")
            if not payload:
                ack_results.append({"id": q_id, "ok": False, "error": "Empty payload"})
                continue

            tally_resp = self._call_tally(payload)
            if tally_resp:
                parsed = tally_transport.parse_import_response(tally_resp)
                if parsed["errors"] == 0 and (parsed["created"] or parsed["altered"] or parsed["deleted"]):
                    ack_results.append({"id": q_id, "ok": True})
                    logger.info(f"Successfully wrote item {q_id} to Tally")
                elif parsed["errors"] or parsed.get("line_error"):
                    err_msg = tally_resp
                    try:
                        err_root = ET.fromstring(tally_resp)
                        line_err = err_root.find(".//LINEERROR")
                        if line_err is not None and line_err.text:
                            err_msg = line_err.text
                    except Exception:
                        pass
                    ack_results.append({"id": q_id, "ok": False, "error": err_msg})
                else:
                    ack_results.append({
                        "id": q_id, "ok": False,
                        "error": "Ambiguous Tally response: no created/altered/deleted count",
                    })
            else:
                ack_results.append({"id": q_id, "ok": False, "error": "Tally gateway unreachable"})

        if ack_results:
            self._call_odoo("/tally/agent/ack", {"results": ack_results})

    def run(self):
        """Main agent loop."""
        logger.info(f"Starting Tally Sync Agent (Odoo: {self.odoo_url}, Tally: {self.tally_url})")
        try:
            while self.running:
                try:
                    self.heartbeat()
                    self.discover_companies()
                    self.poll_and_push_deltas()
                    self.pull_and_write_outbound()
                except Exception as e:
                    logger.exception("Error in sync cycle: %s", e)
                time.sleep(self.poll_interval)
        except KeyboardInterrupt:
            logger.info("Tally Sync Agent stopped")


def main():
    parser = argparse.ArgumentParser(description="TallyPrime On-Premise Sync Agent")
    parser.add_argument("--odoo-url", default=os.getenv("ODOO_URL", "http://localhost:8069"), help="Odoo base URL")
    parser.add_argument("--token", default=os.getenv("AGENT_TOKEN"), help="Agent Bearer Token")
    parser.add_argument("--tally-host", default=os.getenv("TALLY_HOST", "127.0.0.1"), help="Tally host")
    parser.add_argument("--tally-port", type=int, default=int(os.getenv("TALLY_PORT", 9000)), help="Tally port")
    parser.add_argument("--interval", type=int, default=int(os.getenv("POLL_INTERVAL", 60)), help="Poll interval (seconds)")

    args = parser.parse_args()
    if not args.token:
        parser.error("--token is required (or set AGENT_TOKEN)")
    agent = TallyAgent(
        odoo_url=args.odoo_url,
        token=args.token,
        tally_host=args.tally_host,
        tally_port=args.tally_port,
        poll_interval=args.interval,
    )
    agent.run()


if __name__ == "__main__":
    main()
