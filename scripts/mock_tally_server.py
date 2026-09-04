#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Mock TallyPrime XML Gateway Server for local testing and CI/CD.

Listens on HTTP port 9000 and responds to Tally XML export/import envelopes just like
a real TallyPrime instance.
"""
from http.server import HTTPServer, BaseHTTPRequestHandler
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s [MockTally] %(message)s")
logger = logging.getLogger("MockTally")


DUMMY_GROUPS_XML = """<ENVELOPE>
  <HEADER><VERSION>1</VERSION><STATUS>1</STATUS></HEADER>
  <BODY><DATA><COLLECTION>
    <GROUP NAME="Sundry Debtors"><NAME>Sundry Debtors</NAME><PARENT>Current Assets</PARENT><GUID>grp-debtors-001</GUID><ALTERID>10</ALTERID></GROUP>
    <GROUP NAME="Sundry Creditors"><NAME>Sundry Creditors</NAME><PARENT>Current Liabilities</PARENT><GUID>grp-creditors-001</GUID><ALTERID>11</ALTERID></GROUP>
    <GROUP NAME="Bank Accounts"><NAME>Bank Accounts</NAME><PARENT>Current Assets</PARENT><GUID>grp-bank-001</GUID><ALTERID>12</ALTERID></GROUP>
    <GROUP NAME="Sales Accounts"><NAME>Sales Accounts</NAME><PARENT>Direct Incomes</PARENT><GUID>grp-sales-001</GUID><ALTERID>13</ALTERID></GROUP>
    <GROUP NAME="Purchase Accounts"><NAME>Purchase Accounts</NAME><PARENT>Direct Expenses</PARENT><GUID>grp-purch-001</GUID><ALTERID>14</ALTERID></GROUP>
  </COLLECTION></DATA></BODY>
</ENVELOPE>"""

DUMMY_LEDGERS_XML = """<ENVELOPE>
  <HEADER><VERSION>1</VERSION><STATUS>1</STATUS></HEADER>
  <BODY><DATA><COLLECTION>
    <LEDGER NAME="Bharat Steel &amp; Alloys Pvt Ltd">
      <NAME>Bharat Steel &amp; Alloys Pvt Ltd</NAME>
      <PARENT>Sundry Debtors</PARENT>
      <GUID>led-cust-001</GUID>
      <ALTERID>21</ALTERID>
      <PARTYGSTIN>27AABCS1429B1ZB</PARTYGSTIN>
      <INCOMETAXNUMBER>AABCS1429B</INCOMETAXNUMBER>
      <STATENAME>Maharashtra</STATENAME>
      <COUNTRYNAME>India</COUNTRYNAME>
      <PINCODE>400001</PINCODE>
      <EMAIL>billing@bharatsteel.com</EMAIL>
      <LEDGERPHONE>+91 9820012345</LEDGERPHONE>
      <CREDITLIMIT>500000.00</CREDITLIMIT>
      <ADDRESS.LIST><ADDRESS>Plot 14, MIDC Industrial Area, Andheri East</ADDRESS></ADDRESS.LIST>
    </LEDGER>
    <LEDGER NAME="Apex Industrial Supplies">
      <NAME>Apex Industrial Supplies</NAME>
      <PARENT>Sundry Creditors</PARENT>
      <GUID>led-vend-001</GUID>
      <ALTERID>22</ALTERID>
      <PARTYGSTIN>24AAACA9876C1Z3</PARTYGSTIN>
      <STATENAME>Gujarat</STATENAME>
      <COUNTRYNAME>India</COUNTRYNAME>
      <PINCODE>380001</PINCODE>
      <EMAIL>orders@apexsupplies.in</EMAIL>
    </LEDGER>
    <LEDGER NAME="HDFC Bank Current A/c">
      <NAME>HDFC Bank Current A/c</NAME>
      <PARENT>Bank Accounts</PARENT>
      <GUID>led-bank-001</GUID>
      <ALTERID>23</ALTERID>
    </LEDGER>
    <LEDGER NAME="CGST @ 9%"><NAME>CGST @ 9%</NAME><PARENT>Duties &amp; Taxes</PARENT><TAXTYPE>GST</TAXTYPE><GSTDUTYHEAD>CGST</GSTDUTYHEAD><RATEOFTAXCALCULATION>9.00</RATEOFTAXCALCULATION><GUID>led-cgst-001</GUID><ALTERID>24</ALTERID></LEDGER>
    <LEDGER NAME="SGST @ 9%"><NAME>SGST @ 9%</NAME><PARENT>Duties &amp; Taxes</PARENT><TAXTYPE>GST</TAXTYPE><GSTDUTYHEAD>SGST</GSTDUTYHEAD><RATEOFTAXCALCULATION>9.00</RATEOFTAXCALCULATION><GUID>led-sgst-001</GUID><ALTERID>25</ALTERID></LEDGER>
    <LEDGER NAME="IGST @ 18%"><NAME>IGST @ 18%</NAME><PARENT>Duties &amp; Taxes</PARENT><TAXTYPE>GST</TAXTYPE><GSTDUTYHEAD>IGST</GSTDUTYHEAD><RATEOFTAXCALCULATION>18.00</RATEOFTAXCALCULATION><GUID>led-igst-001</GUID><ALTERID>26</ALTERID></LEDGER>
  </COLLECTION></DATA></BODY>
</ENVELOPE>"""

DUMMY_STOCK_ITEMS_XML = """<ENVELOPE>
  <HEADER><VERSION>1</VERSION><STATUS>1</STATUS></HEADER>
  <BODY><DATA><COLLECTION>
    <STOCKITEM NAME="Industrial Hydraulic Valve 50mm">
      <NAME>Industrial Hydraulic Valve 50mm</NAME>
      <PARENT>Valves &amp; Fittings</PARENT>
      <BASEUNITS>Nos</BASEUNITS>
      <HSNCODE>84818030</HSNCODE>
      <OPENINGBALANCE>50 Nos</OPENINGBALANCE>
      <OPENINGRATE>1200.00</OPENINGRATE>
      <OPENINGVALUE>-60000.00</OPENINGVALUE>
      <GUID>item-valve-001</GUID>
      <ALTERID>31</ALTERID>
    </STOCKITEM>
    <STOCKITEM NAME="High Pressure Steel Pipe 2-inch">
      <NAME>High Pressure Steel Pipe 2-inch</NAME>
      <PARENT>Pipes &amp; Tubes</PARENT>
      <BASEUNITS>Mtr</BASEUNITS>
      <HSNCODE>73063000</HSNCODE>
      <OPENINGBALANCE>200 Mtr</OPENINGBALANCE>
      <OPENINGRATE>450.00</OPENINGRATE>
      <OPENINGVALUE>-90000.00</OPENINGVALUE>
      <GUID>item-pipe-001</GUID>
      <ALTERID>32</ALTERID>
    </STOCKITEM>
  </COLLECTION></DATA></BODY>
</ENVELOPE>"""

DUMMY_UNITS_XML = """<ENVELOPE>
  <HEADER><VERSION>1</VERSION><STATUS>1</STATUS></HEADER>
  <BODY><DATA><COLLECTION>
    <UNIT NAME="Nos"><NAME>Nos</NAME><ORIGINALNAME>Numbers</ORIGINALNAME><DECIMALPLACES>0</DECIMALPLACES><GSTREPUOM>NOS</GSTREPUOM><GUID>uom-nos-001</GUID><ALTERID>41</ALTERID></UNIT>
    <UNIT NAME="Mtr"><NAME>Mtr</NAME><ORIGINALNAME>Meters</ORIGINALNAME><DECIMALPLACES>2</DECIMALPLACES><GSTREPUOM>MTR</GSTREPUOM><GUID>uom-mtr-001</GUID><ALTERID>42</ALTERID></UNIT>
  </COLLECTION></DATA></BODY>
</ENVELOPE>"""

DUMMY_VOUCHERS_XML = """<ENVELOPE>
  <HEADER><VERSION>1</VERSION><STATUS>1</STATUS></HEADER>
  <BODY><DATA><COLLECTION>
    <VOUCHER VCHTYPE="Sales" ACTION="Create">
      <GUID>vch-sale-001</GUID>
      <ALTERID>51</ALTERID>
      <DATE>20260901</DATE>
      <VOUCHERTYPENAME>Sales</VOUCHERTYPENAME>
      <VOUCHERNUMBER>INV/2026/001</VOUCHERNUMBER>
      <PARTYLEDGERNAME>Bharat Steel &amp; Alloys Pvt Ltd</PARTYLEDGERNAME>
      <REFERENCE>PO-9988</REFERENCE>
      <NARRATION>Standard dispatch of hydraulic valves</NARRATION>
      <ALLINVENTORYENTRIES.LIST>
        <STOCKITEMNAME>Industrial Hydraulic Valve 50mm</STOCKITEMNAME>
        <ACTUALQTY>10 Nos</ACTUALQTY>
        <BILLEDQTY>10 Nos</BILLEDQTY>
        <RATE>1500.00/Nos</RATE>
        <AMOUNT>-15000.00</AMOUNT>
      </ALLINVENTORYENTRIES.LIST>
      <ALLLEDGERENTRIES.LIST>
        <LEDGERNAME>Bharat Steel &amp; Alloys Pvt Ltd</LEDGERNAME>
        <AMOUNT>17700.00</AMOUNT>
        <BILLALLOCATIONS.LIST>
          <NAME>INV/2026/001</NAME>
          <BILLTYPE>New Ref</BILLTYPE>
          <AMOUNT>17700.00</AMOUNT>
        </BILLALLOCATIONS.LIST>
      </ALLLEDGERENTRIES.LIST>
      <ALLLEDGERENTRIES.LIST>
        <LEDGERNAME>Sales Account</LEDGERNAME>
        <AMOUNT>-15000.00</AMOUNT>
      </ALLLEDGERENTRIES.LIST>
      <ALLLEDGERENTRIES.LIST>
        <LEDGERNAME>CGST @ 9%</LEDGERNAME>
        <AMOUNT>-1350.00</AMOUNT>
      </ALLLEDGERENTRIES.LIST>
      <ALLLEDGERENTRIES.LIST>
        <LEDGERNAME>SGST @ 9%</LEDGERNAME>
        <AMOUNT>-1350.00</AMOUNT>
      </ALLLEDGERENTRIES.LIST>
    </VOUCHER>
  </COLLECTION></DATA></BODY>
</ENVELOPE>"""


class MockTallyHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        req_body = self.rfile.read(content_length).decode("utf-8", errors="replace")

        logger.info(f"Received request ({content_length} bytes)")

        # Route responses based on request payload
        if "<REPORTNAME>List of Companies</REPORTNAME>" in req_body or "<TYPE>Company</TYPE>" in req_body:
            resp = """<ENVELOPE>
  <HEADER><VERSION>1</VERSION><STATUS>1</STATUS></HEADER>
  <BODY><DATA><COLLECTION>
    <COMPANY NAME="Scidecs Demo Ltd"><NAME>Scidecs Demo Ltd</NAME><STARTINGFROM>20260401</STARTINGFROM></COMPANY>
    <COMPANY NAME="Acme Trading Corp"><NAME>Acme Trading Corp</NAME><STARTINGFROM>20260401</STARTINGFROM></COMPANY>
  </COLLECTION></DATA></BODY>
</ENVELOPE>"""
        elif ("<TALLYREQUEST>Import Data</TALLYREQUEST>" in req_body
              or ("<TALLYREQUEST>Import</TALLYREQUEST>" in req_body
                  and "<TYPE>Data</TYPE>" in req_body)):
            resp = """<RESPONSE>
  <CREATED>1</CREATED>
  <ALTERED>0</ALTERED>
  <DELETED>0</DELETED>
  <LASTVCHID>1001</LASTVCHID>
  <LASTMID>2001</LASTMID>
  <ERRORS>0</ERRORS>
</RESPONSE>"""
        elif "<ID>Day Book</ID>" in req_body:
            resp = DUMMY_VOUCHERS_XML
        elif "StockItem" in req_body:
            resp = DUMMY_STOCK_ITEMS_XML
        elif "Unit" in req_body:
            resp = DUMMY_UNITS_XML
        elif "Group" in req_body:
            resp = DUMMY_GROUPS_XML
        elif "Ledger" in req_body:
            resp = DUMMY_LEDGERS_XML
        else:
            resp = DUMMY_LEDGERS_XML

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
