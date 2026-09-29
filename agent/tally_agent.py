#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TallyPrime On-Premise Sync Agent (relay).

Runs beside TallyPrime when Odoo cannot reach Tally's XML gateway directly.
It holds no business logic: Odoo supplies every Tally request, the agent
posts it to Tally and relays the raw response back. Standard library only;
a single file you can copy to the Tally PC.

Loop:
1. heartbeat -> Odoo returns the structure requests and the pull plan when a
   pull is due; the agent runs them and relays all responses in one call.
2. pull outbound queue (masters first) -> import into Tally -> ask Odoo for the
   identity read-back request -> relay the response with the acknowledgement.
"""
import argparse
import json
import logging
import os
import re
import sys
import time
import urllib.error
import urllib.request

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("TallySyncAgent")

COMPANY_LIST_XML = """<ENVELOPE><HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST>
<TYPE>Collection</TYPE><ID>OtiCompanies</ID></HEADER><BODY><DESC><STATICVARIABLES>
<SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT></STATICVARIABLES><TDL><TDLMESSAGE>
<COLLECTION NAME="OtiCompanies" ISMODIFY="No"><TYPE>Company</TYPE><FETCH>Name</FETCH></COLLECTION>
</TDLMESSAGE></TDL></DESC></BODY></ENVELOPE>"""


def parse_import_response(text):
    """Counts and first LINEERROR from a Tally import reply."""
    def _int(tag):
        m = re.search(r"<%s>(-?\d+)</%s>" % (tag, tag), text or "")
        return int(m.group(1)) if m else 0
    m = re.search(r"<LINEERROR>(.*?)</LINEERROR>", text or "", re.S)
    line_error = m.group(1).strip() if m else None
    return {
        "created": _int("CREATED"), "altered": _int("ALTERED"), "deleted": _int("DELETED"),
        "combined": _int("COMBINED"), "ignored": _int("IGNORED"),
        "errors": _int("ERRORS") or _int("EXCEPTIONS") or (1 if line_error else 0),
        "line_error": line_error, "last_vch_id": _int("LASTVCHID"),
    }


class TallyAgent:
    def __init__(self, odoo_url, token, tally_host="127.0.0.1", tally_port=9000, poll_interval=60):
        self.odoo_url = odoo_url.rstrip("/")
        self.token = token
        self.tally_url = f"http://{tally_host}:{tally_port}"
        self.poll_interval = poll_interval
        self.running = True

    def _call_odoo(self, endpoint, payload=None, timeout=300):
        url = f"{self.odoo_url}{endpoint}"
        body = json.dumps({"jsonrpc": "2.0", "params": payload or {}}).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST", headers={
            "Content-Type": "application/json", "X-Tally-Token": self.token})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logger.error("Odoo call %s failed: %s", endpoint, e)
            return None
        if "error" in data:
            logger.error("Odoo error on %s: %s", endpoint, data["error"])
            return None
        result = data.get("result") or {}
        if isinstance(result, dict) and result.get("error"):
            logger.error("Odoo refused %s: %s", endpoint, result["error"])
            return None
        return result

    def _call_tally(self, xml_payload, timeout=300):
        req = urllib.request.Request(self.tally_url, data=(xml_payload or "").encode("utf-8"),
                                     method="POST", headers={"Content-Type": "text/xml;charset=utf-8"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")

    def discover_companies(self):
        try:
            names = re.findall(r'<COMPANY NAME="([^"]+)"', self._call_tally(COMPANY_LIST_XML, timeout=30))
        except Exception as e:
            logger.warning("Company discovery failed: %s", e)
            return
        if names:
            self._call_odoo("/tally/agent/companies", {"companies": sorted(set(names))})

    def pull_from_tally(self, hb):
        """Run the Odoo-built export requests and relay the raw responses."""
        structure = {}
        for key, xml in (hb.get("structure_requests") or {}).items():
            try:
                structure[key] = self._call_tally(xml)
            except Exception as e:
                logger.warning("Structure request %s failed: %s", key, e)
                if key in ("groups", "ledgers"):
                    return
        steps = []
        for key, xml in hb.get("pull_plan") or []:
            try:
                steps.append([key, self._call_tally(xml) if xml else None])
            except Exception as e:
                logger.error("Pull step %s failed: %s", key, e)
                return
        res = self._call_odoo("/tally/agent/push", {"structure": structure, "steps": steps}, timeout=1800)
        if res:
            logger.info("Pull relayed: %s record(s) processed, failed steps: %s",
                        res.get("processed"), res.get("failed"))

    def push_to_tally(self):
        """Import pending Odoo changes into Tally and acknowledge with identity."""
        res = self._call_odoo("/tally/agent/pull", {"limit": 50})
        items = (res or {}).get("items") or []
        if not items:
            return
        acks = []
        for item in items:
            if item.get("verify_request"):
                # Tally matches date + number across voucher types: only send when
                # exactly the linked voucher carries that date and number.
                try:
                    guids = re.findall(r"<GUID[^>]*>([^<]+)</GUID>", self._call_tally(item["verify_request"], timeout=60))
                except Exception as e:
                    acks.append({"id": item["id"], "ok": False, "error": "Tally unreachable: %s" % e})
                    break
                if guids != [item.get("expected_guid")]:
                    acks.append({"id": item["id"], "ok": False,
                                 "error": "Ambiguous Tally voucher number; edit this voucher in Tally."})
                    continue
            try:
                parsed = parse_import_response(self._call_tally(item.get("payload") or ""))
            except Exception as e:
                acks.append({"id": item["id"], "ok": False, "error": "Tally unreachable: %s" % e})
                break
            changed = sum(parsed[k] for k in ("created", "altered", "deleted", "combined", "ignored"))
            if parsed["errors"] or parsed["line_error"] or not changed:
                acks.append({"id": item["id"], "ok": False,
                             "error": parsed["line_error"] or "Ambiguous Tally response"})
                continue
            ack = {"id": item["id"], "ok": True, "last_vch_id": parsed["last_vch_id"]}
            ident = self._call_odoo("/tally/agent/identity",
                                    {"item_id": item["id"], "last_vch_id": parsed["last_vch_id"]})
            if ident and ident.get("request"):
                try:
                    ack["identity_response"] = self._call_tally(ident["request"], timeout=60)
                except Exception as e:
                    logger.warning("Identity read-back failed for item %s: %s", item["id"], e)
            acks.append(ack)
        self._call_odoo("/tally/agent/ack", {"results": acks})
        logger.info("Pushed %s item(s) to Tally", len(acks))

    def run(self):
        logger.info("Tally Sync Agent (Odoo: %s, Tally: %s)", self.odoo_url, self.tally_url)
        while self.running:
            try:
                hb = self._call_odoo("/tally/agent/heartbeat")
                if hb:
                    self.poll_interval = int(hb.get("poll_interval") or self.poll_interval)
                    self.discover_companies()
                    # Push first: Odoo-created objects must be bound before the
                    # next pull reads them back.
                    self.push_to_tally()
                    if hb.get("pull_due"):
                        self.pull_from_tally(hb)
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.exception("Sync cycle failed: %s", e)
            time.sleep(self.poll_interval)


def main():
    parser = argparse.ArgumentParser(description="TallyPrime On-Premise Sync Agent")
    parser.add_argument("--odoo-url", default=os.getenv("ODOO_URL", "http://localhost:8069"))
    parser.add_argument("--token", default=os.getenv("AGENT_TOKEN"))
    parser.add_argument("--tally-host", default=os.getenv("TALLY_HOST", "127.0.0.1"))
    parser.add_argument("--tally-port", type=int, default=int(os.getenv("TALLY_PORT", 9000)))
    parser.add_argument("--interval", type=int, default=int(os.getenv("POLL_INTERVAL", 60)))
    parser.add_argument("--once", action="store_true", help="Run a single sync cycle and exit.")
    args = parser.parse_args()
    if not args.token:
        parser.error("--token is required (or set AGENT_TOKEN)")
    agent = TallyAgent(args.odoo_url, args.token, args.tally_host, args.tally_port, args.interval)
    if args.once:
        agent.running = False
        hb = agent._call_odoo("/tally/agent/heartbeat")
        if hb:
            agent.push_to_tally()
            if hb.get("pull_due"):
                agent.pull_from_tally(hb)
        return
    agent.run()


if __name__ == "__main__":
    main()
