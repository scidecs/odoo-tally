#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stateful Mock TallyPrime XML Gateway Server for local testing and disaster recovery simulation.

Listens on HTTP port 9000 (or custom port) and responds to Tally XML export/import envelopes.
Dynamically stores imported masters and vouchers in memory so that subsequent export requests
return the exact data that was pushed to it, enabling full disaster recovery testing.
"""
from http.server import HTTPServer, BaseHTTPRequestHandler
import logging
import re
import sys
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape as xml_escape

logging.basicConfig(level=logging.INFO, format="%(asctime)s [MockTally] %(message)s")
logger = logging.getLogger("MockTally")


class TallyStore:
    def __init__(self):
        self.companies = ["Scidecs Demo Pvt Ltd", "Scidecs Demo Ltd", "Acme Trading Corp"]
        self.groups = {}
        self.ledgers = {}
        self.units = {
            "Nos": {"name": "Nos", "originalname": "Numbers", "decimal_places": 0, "guid": "uom-nos-001"},
            "Units": {"name": "Units", "originalname": "Units", "decimal_places": 0, "guid": "uom-units-001"},
            "Mtr": {"name": "Mtr", "originalname": "Meters", "decimal_places": 2, "guid": "uom-mtr-001"},
        }
        self.stock_groups = {}
        self.stock_items = {}
        self.godowns = {}
        self.cost_centres = {}
        self.vouchers = {}
        self._init_defaults()

    def _init_defaults(self):
        default_groups = [
            ("Sundry Debtors", "Current Assets"),
            ("Sundry Creditors", "Current Liabilities"),
            ("Bank Accounts", "Current Assets"),
            ("Sales Accounts", "Direct Incomes"),
            ("Purchase Accounts", "Direct Expenses"),
            ("Indirect Expenses", "Primary"),
            ("Direct Expenses", "Primary"),
            ("Direct Incomes", "Primary"),
            ("Indirect Incomes", "Primary"),
            ("Duties & Taxes", "Current Liabilities"),
        ]
        for name, parent in default_groups:
            self.groups[name] = {"name": name, "parent": parent, "guid": f"grp-{name.lower().replace(' ', '-')}"}

        default_ledgers = [
            {"name": "HDFC Bank Current A/c", "parent": "Bank Accounts", "guid": "led-bank-hdfc"},
            {"name": "Cash", "parent": "Cash-in-Hand", "guid": "led-cash-001"},
            {"name": "Sales Account", "parent": "Sales Accounts", "guid": "led-sales-001"},
            {"name": "Purchase Account", "parent": "Purchase Accounts", "guid": "led-purch-001"},
            {"name": "CGST @ 9%", "parent": "Duties & Taxes", "tax_type": "GST", "head": "CGST", "rate": 9.0, "guid": "led-cgst-9"},
            {"name": "SGST @ 9%", "parent": "Duties & Taxes", "tax_type": "GST", "head": "SGST", "rate": 9.0, "guid": "led-sgst-9"},
            {"name": "IGST @ 18%", "parent": "Duties & Taxes", "tax_type": "GST", "head": "IGST", "rate": 18.0, "guid": "led-igst-18"},
        ]
        for l in default_ledgers:
            self.ledgers[l["name"]] = l

    def import_xml(self, xml_text):
        created = 0
        altered = 0
        messages = re.findall(r"(<TALLYMESSAGE[\s\S]*?</TALLYMESSAGE>)", xml_text or "")
        if not messages and "<VOUCHER" in xml_text:
            messages = [xml_text]

        for msg in messages:
            # Stock Group
            m = re.search(r"<STOCKGROUP\s+NAME=\"([^\"]+)\"[\s\S]*?</STOCKGROUP>", msg)
            if m:
                name = m.group(1)
                guid_m = re.search(r"<GUID>(.*?)</GUID>", msg)
                parent_m = re.search(r"<PARENT>(.*?)</PARENT>", msg)
                self.stock_groups[name] = {
                    "name": name,
                    "parent": parent_m.group(1) if parent_m else "Primary",
                    "guid": guid_m.group(1) if guid_m else f"stkgrp-{len(self.stock_groups)+1}",
                    "xml": msg,
                }
                created += 1
                continue

            # Stock Item
            m = re.search(r"<STOCKITEM\s+NAME=\"([^\"]+)\"[\s\S]*?</STOCKITEM>", msg)
            if m:
                name = m.group(1)
                guid_m = re.search(r"<GUID>(.*?)</GUID>", msg)
                parent_m = re.search(r"<PARENT>(.*?)</PARENT>", msg)
                uom_m = re.search(r"<BASEUNITS>(.*?)</BASEUNITS>", msg)
                hsn_m = re.search(r"<HSNCODE>(.*?)</HSNCODE>", msg)
                self.stock_items[name] = {
                    "name": name,
                    "parent": parent_m.group(1) if parent_m else "Primary",
                    "base_uom": uom_m.group(1) if uom_m else "Nos",
                    "hsn": hsn_m.group(1) if hsn_m else "",
                    "guid": guid_m.group(1) if guid_m else f"item-{len(self.stock_items)+1}",
                    "xml": msg,
                }
                created += 1
                continue

            # Unit
            m = re.search(r"<UNIT\s+NAME=\"([^\"]+)\"[\s\S]*?</UNIT>", msg)
            if m:
                name = m.group(1)
                guid_m = re.search(r"<GUID>(.*?)</GUID>", msg)
                self.units[name] = {
                    "name": name,
                    "originalname": name,
                    "guid": guid_m.group(1) if guid_m else f"uom-{len(self.units)+1}",
                }
                created += 1
                continue

            # Godown
            m = re.search(r"<GODOWN\s+NAME=\"([^\"]+)\"[\s\S]*?</GODOWN>", msg)
            if m:
                name = m.group(1)
                guid_m = re.search(r"<GUID>(.*?)</GUID>", msg)
                parent_m = re.search(r"<PARENT>(.*?)</PARENT>", msg)
                self.godowns[name] = {
                    "name": name,
                    "parent": parent_m.group(1) if parent_m else "Primary",
                    "guid": guid_m.group(1) if guid_m else f"gdn-{len(self.godowns)+1}",
                }
                created += 1
                continue

            # Ledger
            m = re.search(r"<LEDGER\s+NAME=\"([^\"]+)\"[\s\S]*?</LEDGER>", msg)
            if m:
                name = m.group(1)
                guid_m = re.search(r"<GUID>(.*?)</GUID>", msg)
                parent_m = re.search(r"<PARENT>(.*?)</PARENT>", msg)
                gstin_m = re.search(r"<PARTYGSTIN>(.*?)</PARTYGSTIN>", msg)
                self.ledgers[name] = {
                    "name": name,
                    "parent": parent_m.group(1) if parent_m else "Sundry Debtors",
                    "gstin": gstin_m.group(1) if gstin_m else "",
                    "guid": guid_m.group(1) if guid_m else f"led-{len(self.ledgers)+1}",
                    "xml": msg,
                }
                created += 1
                continue

            # Voucher
            m = re.search(r"<VOUCHER[\s\S]*?</VOUCHER>", msg)
            if m:
                vch_xml = m.group(0)
                guid_m = re.search(r"<GUID>(.*?)</GUID>", vch_xml)
                vno_m = re.search(r"<VOUCHERNUMBER>(.*?)</VOUCHERNUMBER>", vch_xml)
                guid = guid_m.group(1) if guid_m else f"vch-{len(self.vouchers)+1}"
                self.vouchers[guid] = {
                    "guid": guid,
                    "number": vno_m.group(1) if vno_m else guid,
                    "xml": vch_xml,
                }
                created += 1
                continue

        if created == 0 and len(messages) > 0:
            created = len(messages)
        return max(1, created)

    def export_companies_xml(self):
        items = "\n".join(f'<COMPANY NAME="{xml_escape(c)}"><NAME>{xml_escape(c)}</NAME><STARTINGFROM>20260401</STARTINGFROM></COMPANY>' for c in self.companies)
        return f"""<ENVELOPE>
  <HEADER><VERSION>1</VERSION><STATUS>1</STATUS></HEADER>
  <BODY><DATA><COLLECTION>{items}</COLLECTION></DATA></BODY>
</ENVELOPE>"""

    def export_groups_xml(self):
        items = "\n".join(f'<GROUP NAME="{xml_escape(g["name"])}"><NAME>{xml_escape(g["name"])}</NAME><PARENT>{xml_escape(g.get("parent","Primary"))}</PARENT><GUID>{xml_escape(g.get("guid",""))}</GUID><ALTERID>100</ALTERID></GROUP>' for g in self.groups.values())
        return f"""<ENVELOPE>
  <HEADER><VERSION>1</VERSION><STATUS>1</STATUS></HEADER>
  <BODY><DATA><COLLECTION>{items}</COLLECTION></DATA></BODY>
</ENVELOPE>"""

    def export_ledgers_xml(self):
        res = []
        for l in self.ledgers.values():
            if "xml" in l:
                clean = re.sub(r'<TALLYMESSAGE[^>]*>', '', l["xml"]).replace('</TALLYMESSAGE>', '').strip()
                res.append(clean)
            else:
                res.append(f'<LEDGER NAME="{xml_escape(l["name"])}"><NAME>{xml_escape(l["name"])}</NAME><PARENT>{xml_escape(l.get("parent","Sundry Debtors"))}</PARENT><GUID>{xml_escape(l.get("guid",""))}</GUID><ALTERID>200</ALTERID></LEDGER>')
        return f"""<ENVELOPE>
  <HEADER><VERSION>1</VERSION><STATUS>1</STATUS></HEADER>
  <BODY><DATA><COLLECTION>{chr(10).join(res)}</COLLECTION></DATA></BODY>
</ENVELOPE>"""

    def export_units_xml(self):
        items = "\n".join(f'<UNIT NAME="{xml_escape(u["name"])}"><NAME>{xml_escape(u["name"])}</NAME><ORIGINALNAME>{xml_escape(u.get("originalname", u["name"]))}</ORIGINALNAME><DECIMALPLACES>{u.get("decimal_places", 0)}</DECIMALPLACES><GUID>{xml_escape(u.get("guid",""))}</GUID><ALTERID>300</ALTERID></UNIT>' for u in self.units.values())
        return f"""<ENVELOPE>
  <HEADER><VERSION>1</VERSION><STATUS>1</STATUS></HEADER>
  <BODY><DATA><COLLECTION>{items}</COLLECTION></DATA></BODY>
</ENVELOPE>"""

    def export_stock_groups_xml(self):
        items = []
        for g in self.stock_groups.values():
            if "xml" in g:
                clean = re.sub(r'<TALLYMESSAGE[^>]*>', '', g["xml"]).replace('</TALLYMESSAGE>', '').strip()
                items.append(clean)
            else:
                items.append(f'<STOCKGROUP NAME="{xml_escape(g["name"])}"><NAME>{xml_escape(g["name"])}</NAME><PARENT>{xml_escape(g.get("parent","Primary"))}</PARENT><GUID>{xml_escape(g.get("guid",""))}</GUID><ALTERID>400</ALTERID></STOCKGROUP>')
        return f"""<ENVELOPE>
  <HEADER><VERSION>1</VERSION><STATUS>1</STATUS></HEADER>
  <BODY><DATA><COLLECTION>{chr(10).join(items)}</COLLECTION></DATA></BODY>
</ENVELOPE>"""

    def export_stock_items_xml(self):
        items = []
        for item in self.stock_items.values():
            if "xml" in item:
                clean = re.sub(r'<TALLYMESSAGE[^>]*>', '', item["xml"]).replace('</TALLYMESSAGE>', '').strip()
                items.append(clean)
            else:
                items.append(f'<STOCKITEM NAME="{xml_escape(item["name"])}"><NAME>{xml_escape(item["name"])}</NAME><PARENT>{xml_escape(item.get("parent","Primary"))}</PARENT><BASEUNITS>{xml_escape(item.get("base_uom","Nos"))}</BASEUNITS><GUID>{xml_escape(item.get("guid",""))}</GUID><ALTERID>500</ALTERID></STOCKITEM>')
        return f"""<ENVELOPE>
  <HEADER><VERSION>1</VERSION><STATUS>1</STATUS></HEADER>
  <BODY><DATA><COLLECTION>{chr(10).join(items)}</COLLECTION></DATA></BODY>
</ENVELOPE>"""

    def export_godowns_xml(self):
        items = "\n".join(f'<GODOWN NAME="{xml_escape(g["name"])}"><NAME>{xml_escape(g["name"])}</NAME><PARENT>{xml_escape(g.get("parent","Primary"))}</PARENT><GUID>{xml_escape(g.get("guid",""))}</GUID><ALTERID>600</ALTERID></GODOWN>' for g in self.godowns.values())
        return f"""<ENVELOPE>
  <HEADER><VERSION>1</VERSION><STATUS>1</STATUS></HEADER>
  <BODY><DATA><COLLECTION>{items}</COLLECTION></DATA></BODY>
</ENVELOPE>"""

    def export_vouchers_xml(self):
        items = []
        for v in self.vouchers.values():
            clean = re.sub(r'<TALLYMESSAGE[^>]*>', '', v["xml"]).replace('</TALLYMESSAGE>', '').strip()
            items.append(clean)
        return f"""<ENVELOPE>
  <HEADER><VERSION>1</VERSION><STATUS>1</STATUS></HEADER>
  <BODY><DATA><COLLECTION>{chr(10).join(items)}</COLLECTION></DATA></BODY>
</ENVELOPE>"""


STORE = TallyStore()


class MockTallyHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        req_body = self.rfile.read(content_length).decode("utf-8", errors="replace")

        logger.info(f"Received request ({content_length} bytes)")

        # 1. Company List
        if "<REPORTNAME>List of Companies</REPORTNAME>" in req_body or "<TYPE>Company</TYPE>" in req_body:
            resp = STORE.export_companies_xml()

        # 2. Import Data
        elif ("<TALLYREQUEST>Import Data</TALLYREQUEST>" in req_body
              or ("<TALLYREQUEST>Import</TALLYREQUEST>" in req_body and "<TYPE>Data</TYPE>" in req_body)):
            count = STORE.import_xml(req_body)
            resp = f"""<ENVELOPE>
  <HEADER><VERSION>1</VERSION><STATUS>1</STATUS></HEADER>
  <BODY><DATA><IMPORTRESULT>
    <CREATED>{count}</CREATED>
    <ALTERED>0</ALTERED>
    <DELETED>0</DELETED>
    <LASTVCHID>1001</LASTVCHID>
    <LASTMID>2001</LASTMID>
    <COMBINED>0</COMBINED>
    <IGNORED>0</IGNORED>
    <ERRORS>0</ERRORS>
    <CANCELLED>0</CANCELLED>
    <EXCEPTIONS>0</EXCEPTIONS>
  </IMPORTRESULT></DATA></BODY>
</ENVELOPE>"""

        # 3. Export Day Book / Vouchers
        elif "<ID>Day Book</ID>" in req_body or "<TYPE>Voucher</TYPE>" in req_body:
            resp = STORE.export_vouchers_xml()

        # 4. Export Masters
        elif "StockItem" in req_body:
            resp = STORE.export_stock_items_xml()
        elif "StockGroup" in req_body:
            resp = STORE.export_stock_groups_xml()
        elif "Unit" in req_body:
            resp = STORE.export_units_xml()
        elif "Godown" in req_body:
            resp = STORE.export_godowns_xml()
        elif "Group" in req_body:
            resp = STORE.export_groups_xml()
        elif "Ledger" in req_body:
            resp = STORE.export_ledgers_xml()
        else:
            resp = STORE.export_ledgers_xml()

        self.send_response(200)
        self.send_header("Content-Type", "text/xml;charset=utf-8")
        self.send_header("Content-Length", str(len(resp.encode("utf-8"))))
        self.end_headers()
        self.wfile.write(resp.encode("utf-8"))

    def log_message(self, format, *args):
        pass


def run_server(port=9000):
    server = HTTPServer(("0.0.0.0", port), MockTallyHandler)
    logger.info(f"Mock Tally Server running on port {port}...")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Stopping Mock Tally Server")
        server.server_close()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9000
    run_server(port)
