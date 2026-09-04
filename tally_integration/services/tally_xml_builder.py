# -*- coding: utf-8 -*-
"""Builder service for constructing Tally XML requests and import envelopes.

Builds standard Tally XML messages for:
- Master records (Groups, Ledgers, Parties, UoMs, Stock Items, Cost Centres, Taxes, Godowns)
- Voucher transactions (Sales, Purchase, Credit/Debit Note, Receipts, Payments, Journals, Contras)
- Export / AlterID query requests (TDL Collections)
"""
import html
from xml.sax.saxutils import escape


def xml_escape(value):
    """Safely escape text for XML elements."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return escape(str(value))


def format_tally_date(dt, educational_mode=False):
    """Format datetime or date into Tally YYYYMMDD string format with optional educational mode translation."""
    if not dt:
        return ""
    if hasattr(dt, "strftime"):
        clean = dt.strftime("%Y%m%d")
    else:
        clean = str(dt).replace("-", "").replace("/", "")[:8]
    if len(clean) == 8 and educational_mode:
        # In Tally Educational mode, vouchers are only accepted on days 1, 2, and 31.
        day = int(clean[6:8])
        if day not in (1, 2, 31):
            clean = f"{clean[:6]}01"
    return clean



def wrap_import_envelope(tally_messages, company_name=None, report_type="All Masters"):
    """Wrap one or more <TALLYMESSAGE> items inside a valid Tally import envelope."""
    body_content = "\n".join(tally_messages)
    company_tag = (f"<SVCURRENTCOMPANY>{xml_escape(company_name)}</SVCURRENTCOMPANY>"
                   if company_name else "")
    return f"""<ENVELOPE>
  <HEADER>
    <VERSION>1</VERSION>
    <TALLYREQUEST>Import</TALLYREQUEST>
    <TYPE>Data</TYPE>
    <ID>{xml_escape(report_type)}</ID>
  </HEADER>
  <BODY>
    <DESC>
      <STATICVARIABLES>
        <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
        {company_tag}
      </STATICVARIABLES>
    </DESC>
    <DATA>
{body_content}
    </DATA>
  </BODY>
</ENVELOPE>"""


def wrap_export_request(report_name, company_name=None, static_vars=None, tdl_collection=None):
    """Build a TDL export request envelope for polling or fetching data."""
    vars_xml = ["<SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>"]
    if company_name:
        vars_xml.append(f"<SVCURRENTCOMPANY>{xml_escape(company_name)}</SVCURRENTCOMPANY>")
    if static_vars:
        for k, v in static_vars.items():
            if k != "SVEXPORTFORMAT":
                vars_xml.append(f"<{k}>{xml_escape(v)}</{k}>")
    vars_str = "\n          ".join(vars_xml)

    tdl_xml = f"\n    <TDL>{tdl_collection}</TDL>" if tdl_collection else ""

    return f"""<ENVELOPE>
  <HEADER>
    <TALLYREQUEST>Export Data</TALLYREQUEST>
  </HEADER>
  <BODY>
    <EXPORTDATA>
      <REQUESTDESC>
        <REPORTNAME>{xml_escape(report_name)}</REPORTNAME>
        <STATICVARIABLES>
        {vars_str}
        </STATICVARIABLES>
      </REQUESTDESC>{tdl_xml}
    </EXPORTDATA>
  </BODY>
</ENVELOPE>"""


# ==============================================================================
# MASTER XML BUILDERS
# ==============================================================================

def build_group_xml(name, parent="Primary", nature=None, guid=None):
    """Build <GROUP> XML."""
    guid_tag = f'<GUID>{xml_escape(guid)}</GUID>' if guid else ''
    nature_tag = f'<NATUREOFGROUP>{xml_escape(nature)}</NATUREOFGROUP>' if nature else ''
    return f"""<TALLYMESSAGE xmlns:UDF="TallyUDF">
  <GROUP NAME="{xml_escape(name)}" ACTION="Create">
    {guid_tag}
    <NAME>{xml_escape(name)}</NAME>
    <PARENT>{xml_escape(parent or 'Primary')}</PARENT>
    <ISSUBLEDGER>No</ISSUBLEDGER>
    <ISBILLWISEON>No</ISBILLWISEON>
    <ISCOSTCENTRESON>No</ISCOSTCENTRESON>
    {nature_tag}
  </GROUP>
</TALLYMESSAGE>"""


def build_account_ledger_xml(name, parent="Indirect Expenses", opening_balance=0.0,
                             is_billwise=False, currency="INR", description=None, guid=None):
    """Build General Account <LEDGER> XML."""
    guid_tag = f'<GUID>{xml_escape(guid)}</GUID>' if guid else ''
    op_bal_tag = f'<OPENINGBALANCE>{float(opening_balance or 0.0):.2f}</OPENINGBALANCE>' if opening_balance else ''
    desc_tag = f'<DESCRIPTION>{xml_escape(description)}</DESCRIPTION>' if description else ''
    return f"""<TALLYMESSAGE xmlns:UDF="TallyUDF">
  <LEDGER NAME="{xml_escape(name)}" ACTION="Create">
    {guid_tag}
    <NAME>{xml_escape(name)}</NAME>
    <PARENT>{xml_escape(parent or 'Indirect Expenses')}</PARENT>
    <ISBILLWISEON>{'Yes' if is_billwise else 'No'}</ISBILLWISEON>
    <ISCOSTCENTRESON>No</ISCOSTCENTRESON>
    <CURRENCYNAME>{xml_escape(currency or 'INR')}</CURRENCYNAME>
    {op_bal_tag}
    {desc_tag}
  </LEDGER>
</TALLYMESSAGE>"""


def build_party_ledger_xml(name, parent="Sundry Debtors", gstin=None, pan=None,
                           address_lines=None, state_name=None, country_name="India",
                           pincode=None, email=None, phone=None, credit_limit=0.0,
                           opening_balance=0.0, guid=None):
    """Build Party (Customer / Vendor) <LEDGER> XML with full Indian GST details."""
    guid_tag = f'<GUID>{xml_escape(guid)}</GUID>' if guid else ''
    gstin_tag = f'<PARTYGSTIN>{xml_escape(gstin)}</PARTYGSTIN><GSTREGISTRATIONTYPE>{"Regular" if gstin else "Unregistered"}</GSTREGISTRATIONTYPE>' if gstin else '<GSTREGISTRATIONTYPE>Unregistered</GSTREGISTRATIONTYPE>'
    pan_tag = f'<INCOMETAXNUMBER>{xml_escape(pan)}</INCOMETAXNUMBER>' if pan else ''
    state_tag = f'<STATENAME>{xml_escape(state_name)}</STATENAME>' if state_name else ''
    country_tag = f'<COUNTRYNAME>{xml_escape(country_name or "India")}</COUNTRYNAME>'
    pincode_tag = f'<PINCODE>{xml_escape(pincode)}</PINCODE>' if pincode else ''
    email_tag = f'<EMAIL>{xml_escape(email)}</EMAIL>' if email else ''
    phone_tag = f'<LEDGERPHONE>{xml_escape(phone)}</LEDGERPHONE>' if phone else ''
    credit_tag = f'<CREDITLIMIT>{float(credit_limit or 0.0):.2f}</CREDITLIMIT>' if credit_limit else ''
    op_bal_tag = f'<OPENINGBALANCE>{float(opening_balance or 0.0):.2f}</OPENINGBALANCE>' if opening_balance else ''

    addr_xml = ""
    if address_lines:
        lines = [f"<ADDRESS>{xml_escape(line.strip())}</ADDRESS>" for line in address_lines if line and line.strip()]
        if lines:
            addr_xml = f"<ADDRESS.LIST>\n        " + "\n        ".join(lines) + "\n      </ADDRESS.LIST>"

    return f"""<TALLYMESSAGE xmlns:UDF="TallyUDF">
  <LEDGER NAME="{xml_escape(name)}" ACTION="Create">
    {guid_tag}
    <NAME>{xml_escape(name)}</NAME>
    <PARENT>{xml_escape(parent or 'Sundry Debtors')}</PARENT>
    <ISBILLWISEON>Yes</ISBILLWISEON>
    <AFFECTSSTOCK>No</AFFECTSSTOCK>
    {gstin_tag}
    {pan_tag}
    {state_tag}
    {country_tag}
    {pincode_tag}
    {email_tag}
    {phone_tag}
    {credit_tag}
    {op_bal_tag}
    {addr_xml}
  </LEDGER>
</TALLYMESSAGE>"""


def build_unit_xml(name, formal_name=None, decimal_places=0, uqc=None, guid=None):
    """Build <UNIT> XML."""
    guid_tag = f'<GUID>{xml_escape(guid)}</GUID>' if guid else ''
    uqc_tag = f'<GSTREPUOM>{xml_escape(uqc)}</GSTREPUOM>' if uqc else ''
    return f"""<TALLYMESSAGE xmlns:UDF="TallyUDF">
  <UNIT NAME="{xml_escape(name)}" ACTION="Create">
    {guid_tag}
    <NAME>{xml_escape(name)}</NAME>
    <ISSIMPLEUNIT>Yes</ISSIMPLEUNIT>
    <ORIGINALNAME>{xml_escape(formal_name or name)}</ORIGINALNAME>
    <DECIMALPLACES>{int(decimal_places or 0)}</DECIMALPLACES>
    {uqc_tag}
  </UNIT>
</TALLYMESSAGE>"""


def build_stock_group_xml(name, parent="Primary", guid=None):
    """Build <STOCKGROUP> XML."""
    guid_tag = f'<GUID>{xml_escape(guid)}</GUID>' if guid else ''
    return f"""<TALLYMESSAGE xmlns:UDF="TallyUDF">
  <STOCKGROUP NAME="{xml_escape(name)}" ACTION="Create">
    {guid_tag}
    <NAME>{xml_escape(name)}</NAME>
    <PARENT>{xml_escape(parent or 'Primary')}</PARENT>
    <ISADDABLE>Yes</ISADDABLE>
  </STOCKGROUP>
</TALLYMESSAGE>"""


def build_stock_item_xml(name, base_uom="Nos", parent_group="Primary", hsn_code=None,
                         gst_rate=0.0, standard_cost=0.0, sale_price=0.0,
                         opening_qty=0.0, opening_rate=0.0, guid=None):
    """Build <STOCKITEM> XML."""
    guid_tag = f'<GUID>{xml_escape(guid)}</GUID>' if guid else ''
    hsn_tag = f'<HSNCODE>{xml_escape(hsn_code)}</HSNCODE>' if hsn_code else ''
    gst_tag = f'<GSTRATEDETAILS.LIST><GSTRATE>{float(gst_rate or 0.0):.2f}</GSTRATE></GSTRATEDETAILS.LIST>' if gst_rate else ''
    cost_tag = f'<STANDARDCOSTLIST.LIST><RATE>{float(standard_cost or 0.0):.2f}</RATE></STANDARDCOSTLIST.LIST>' if standard_cost else ''
    price_tag = f'<STANDARDPRICELIST.LIST><RATE>{float(sale_price or 0.0):.2f}</RATE></STANDARDPRICELIST.LIST>' if sale_price else ''

    op_val = float(opening_qty or 0) * float(opening_rate or 0)
    op_xml = f"""<OPENINGBALANCE>{float(opening_qty):.2f} {xml_escape(base_uom)}</OPENINGBALANCE>
    <OPENINGRATE>{float(opening_rate):.2f}</OPENINGRATE>
    <OPENINGVALUE>-{op_val:.2f}</OPENINGVALUE>""" if opening_qty else ""

    parent_tag = f"<PARENT>{xml_escape(parent_group)}</PARENT>" if parent_group and parent_group != "Primary" else ""

    return f"""<TALLYMESSAGE xmlns:UDF="TallyUDF">
  <STOCKITEM NAME="{xml_escape(name)}" ACTION="Create">
    {guid_tag}
    <NAME>{xml_escape(name)}</NAME>
    {parent_tag}
    <BASEUNITS>{xml_escape(base_uom or 'Nos')}</BASEUNITS>
    {hsn_tag}
    {gst_tag}
    {cost_tag}
    {price_tag}
    {op_xml}
  </STOCKITEM>
</TALLYMESSAGE>"""


def build_cost_centre_xml(name, parent=None, category="Primary Cost Category", guid=None):
    """Build <COSTCENTRE> XML."""
    guid_tag = f'<GUID>{xml_escape(guid)}</GUID>' if guid else ''
    parent_tag = f'<PARENT>{xml_escape(parent)}</PARENT>' if parent else ''
    return f"""<TALLYMESSAGE xmlns:UDF="TallyUDF">
  <COSTCENTRE NAME="{xml_escape(name)}" ACTION="Create">
    {guid_tag}
    <NAME>{xml_escape(name)}</NAME>
    <CATEGORYNAME>{xml_escape(category or 'Primary Cost Category')}</CATEGORYNAME>
    {parent_tag}
  </COSTCENTRE>
</TALLYMESSAGE>"""


def build_godown_xml(name, parent="Main Location", guid=None):
    """Build <GODOWN> XML."""
    guid_tag = f'<GUID>{xml_escape(guid)}</GUID>' if guid else ''
    return f"""<TALLYMESSAGE xmlns:UDF="TallyUDF">
  <GODOWN NAME="{xml_escape(name)}" ACTION="Create">
    {guid_tag}
    <NAME>{xml_escape(name)}</NAME>
    <PARENT>{xml_escape(parent or 'Primary')}</PARENT>
  </GODOWN>
</TALLYMESSAGE>"""


def build_tax_ledger_xml(name, gst_type="CGST", rate=0.0, parent="Duties & Taxes", guid=None):
    """Build Tax <LEDGER> XML for GST (CGST, SGST, IGST, Cess)."""
    guid_tag = f'<GUID>{xml_escape(guid)}</GUID>' if guid else ''
    return f"""<TALLYMESSAGE xmlns:UDF="TallyUDF">
  <LEDGER NAME="{xml_escape(name)}" ACTION="Create">
    {guid_tag}
    <NAME>{xml_escape(name)}</NAME>
    <PARENT>{xml_escape(parent or 'Duties & Taxes')}</PARENT>
    <TAXTYPE>GST</TAXTYPE>
    <GSTDUTYHEAD>{xml_escape(gst_type.upper())}</GSTDUTYHEAD>
    <RATEOFTAXCALCULATION>{float(rate or 0.0):.2f}</RATEOFTAXCALCULATION>
  </LEDGER>
</TALLYMESSAGE>"""


# ==============================================================================
# VOUCHER XML BUILDERS
# ==============================================================================

def build_voucher_xml(voucher_type, voucher_number, date, party_ledger,
                      ledger_entries=None, inventory_entries=None,
                      narration=None, guid=None, reference=None, is_invoice=True):
    """Build a complete balanced <VOUCHER> XML message for Tally.

    :param voucher_type: Sales, Purchase, Credit Note, Debit Note, Receipt, Payment, Journal, Contra
    :param voucher_number: Invoice / Ref number
    :param date: YYYYMMDD or date object
    :param party_ledger: Name of the party/bank/cash ledger
    :param ledger_entries: list of dicts:
        {'ledger': str, 'amount': float (positive=debit, negative=credit), 'bill_allocations': [{'type': 'Agst Ref'|'New Ref', 'name': str, 'amount': float}], 'cost_centres': [{'name': str, 'amount': float}]}
    :param inventory_entries: list of dicts:
        {'item': str, 'qty': float, 'rate': float, 'amount': float, 'uom': str, 'godown': str, 'discount': float}
    :param narration: string narration
    :param guid: optional GUID
    """
    guid_tag = f'<GUID>{xml_escape(guid)}</GUID>' if guid else ''
    date_str = format_tally_date(date)
    ref_tag = f'<REFERENCE>{xml_escape(reference)}</REFERENCE>' if reference else ''
    narration_tag = f'<NARRATION>{xml_escape(narration)}</NARRATION>' if narration else ''

    # Build Inventory entries
    inv_xml = []
    if inventory_entries:
        for inv in inventory_entries:
            item_name = inv.get("item", "")
            qty = float(inv.get("qty", 0.0))
            uom = inv.get("uom", "Nos")
            rate = float(inv.get("rate", 0.0))
            amount = float(inv.get("amount", 0.0))
            godown = inv.get("godown", "Main Location")
            disc = float(inv.get("discount", 0.0))
            disc_tag = f"<DISCOUNT>{disc:.2f}</DISCOUNT>" if disc else ""

            batch_xml = f"""<BATCHALLOCATIONS.LIST>
            <GODOWNNAME>{xml_escape(godown)}</GODOWNNAME>
            <BATCHNAME>Primary Batch</BATCHNAME>
            <AMOUNT>{amount:.2f}</AMOUNT>
            <ACTUALQTY>{qty:.2f} {xml_escape(uom)}</ACTUALQTY>
            <BILLEDQTY>{qty:.2f} {xml_escape(uom)}</BILLEDQTY>
          </BATCHALLOCATIONS.LIST>"""

            acc_ledger = inv.get("account_ledger")
            acc_alloc_xml = ""
            if acc_ledger:
                acc_alloc_xml = f"""
          <ACCOUNTINGALLOCATIONS.LIST>
            <LEDGERNAME>{xml_escape(acc_ledger)}</LEDGERNAME>
            <ISDEEMEDPOSITIVE>{'Yes' if amount < 0 else 'No'}</ISDEEMEDPOSITIVE>
            <AMOUNT>{amount:.2f}</AMOUNT>
          </ACCOUNTINGALLOCATIONS.LIST>"""

            inv_xml.append(f"""        <ALLINVENTORYENTRIES.LIST>
          <STOCKITEMNAME>{xml_escape(item_name)}</STOCKITEMNAME>
          <ISDEEMEDPOSITIVE>{'Yes' if amount < 0 else 'No'}</ISDEEMEDPOSITIVE>
          <RATE>{rate:.2f}/{xml_escape(uom)}</RATE>
          <AMOUNT>{amount:.2f}</AMOUNT>
          <ACTUALQTY>{qty:.2f} {xml_escape(uom)}</ACTUALQTY>
          <BILLEDQTY>{qty:.2f} {xml_escape(uom)}</BILLEDQTY>
          {disc_tag}
          {batch_xml}{acc_alloc_xml}
        </ALLINVENTORYENTRIES.LIST>""")

    inv_entries_str = "\n".join(inv_xml)

    # Build Ledger entries (including Bill Allocations and Cost Centres)
    led_xml = []
    if ledger_entries:
        for led in ledger_entries:
            led_name = led.get("ledger", "")
            amount = float(led.get("amount", 0.0))
            is_deemed_positive = "Yes" if amount < 0 else "No"

            # Bill Allocations
            bill_allocs = []
            for b in led.get("bill_allocations", []):
                b_type = b.get("type", "Agst Ref")
                b_name = b.get("name", voucher_number)
                b_amt = float(b.get("amount", amount))
                bill_allocs.append(f"""          <BILLALLOCATIONS.LIST>
            <NAME>{xml_escape(b_name)}</NAME>
            <BILLTYPE>{xml_escape(b_type)}</BILLTYPE>
            <AMOUNT>{b_amt:.2f}</AMOUNT>
          </BILLALLOCATIONS.LIST>""")
            bill_alloc_str = "\n".join(bill_allocs)

            # Cost Centres
            cc_allocs = []
            for cc in led.get("cost_centres", []):
                cc_name = cc.get("name", "")
                cc_amt = float(cc.get("amount", amount))
                cc_allocs.append(f"""          <COSTCENTREALLOCATIONS.LIST>
            <NAME>{xml_escape(cc_name)}</NAME>
            <AMOUNT>{cc_amt:.2f}</AMOUNT>
          </COSTCENTREALLOCATIONS.LIST>""")
            cc_alloc_str = "\n".join(cc_allocs)

            led_xml.append(f"""        <ALLLEDGERENTRIES.LIST>
          <LEDGERNAME>{xml_escape(led_name)}</LEDGERNAME>
          <ISDEEMEDPOSITIVE>{is_deemed_positive}</ISDEEMEDPOSITIVE>
          <AMOUNT>{amount:.2f}</AMOUNT>
{bill_alloc_str}
{cc_alloc_str}
        </ALLLEDGERENTRIES.LIST>""")

    led_entries_str = "\n".join(led_xml)

    return f"""<TALLYMESSAGE xmlns:UDF="TallyUDF">
  <VOUCHER VCHTYPE="{xml_escape(voucher_type)}" ACTION="Create" OBJVIEW="Accounting Voucher View">
    {guid_tag}
    <DATE>{date_str}</DATE>
    <EFFECTIVEDATE>{date_str}</EFFECTIVEDATE>
    <VOUCHERTYPENAME>{xml_escape(voucher_type)}</VOUCHERTYPENAME>
    <VOUCHERNUMBER>{xml_escape(voucher_number)}</VOUCHERNUMBER>
    <PARTYLEDGERNAME>{xml_escape(party_ledger)}</PARTYLEDGERNAME>
    <ISINVOICE>{'Yes' if is_invoice else 'No'}</ISINVOICE>
    {ref_tag}
    {narration_tag}
{inv_entries_str}
{led_entries_str}
  </VOUCHER>
</TALLYMESSAGE>"""


def build_currency_xml(name, symbol="₹", formal_name="INR", decimal_symbol="paise",
                       decimal_places=2, guid=None):
    """Build <CURRENCY> XML."""
    guid_tag = f'<GUID>{xml_escape(guid)}</GUID>' if guid else ''
    cur_name = name or symbol or formal_name or "INR"
    return f"""<TALLYMESSAGE xmlns:UDF="TallyUDF">
  <CURRENCY NAME="{xml_escape(cur_name)}" ACTION="Create">
    {guid_tag}
    <NAME>{xml_escape(cur_name)}</NAME>
    <MAILINGNAME>{xml_escape(formal_name or cur_name)}</MAILINGNAME>
    <ORIGINALNAME>{xml_escape(symbol or cur_name)}</ORIGINALNAME>
    <EXPANDEDSYMBOL>{xml_escape(formal_name or cur_name)}</EXPANDEDSYMBOL>
    <DECIMALSYMBOL>{xml_escape(decimal_symbol or 'paise')}</DECIMALSYMBOL>
    <DECIMALPLACES>{int(decimal_places or 2)}</DECIMALPLACES>
  </CURRENCY>
</TALLYMESSAGE>"""


# ==============================================================================
# EXPORT REQUESTS (direct-mode master pull)
# ==============================================================================

# entity -> native Tally collection object name
COLLECTION_MAP = {
    "currency": "Currency",
    "group": "Group",
    "account_ledger": "Ledger",
    "ledger": "Ledger",
    "uom": "Unit",
    "stock_item": "StockItem",
    "cost_centre": "CostCentre",
    "godown": "Godown",
}


def build_collection_export(collection_type, company_name=None, from_alterid=None, fetch_fields=None):
    """Build a Tally 'Export Collection' request for a native object type.

    When ``from_alterid`` is a positive int, an inline TDL defines a filtered
    collection returning only objects with ``$AlterID > from_alterid`` — a
    server-side delta so unchanged masters never cross the wire. Falls back to a
    full collection export when ``from_alterid`` is falsy.
    """
    company_tag = (f"<SVCURRENTCOMPANY>{xml_escape(company_name)}</SVCURRENTCOMPANY>"
                   if company_name else "")
    tdl = ""
    coll_id = collection_type
    if from_alterid and int(from_alterid) > 0:
        coll_id = "Oti%sColl" % collection_type
        filt = "OtiAlt%s" % collection_type
        tdl = f"""
      <TDL>
        <TDLMESSAGE>
          <COLLECTION NAME="{coll_id}" ISMODIFY="No" ISFIXED="No" ISINITIALIZE="No" ISOPTION="No" ISINTERNAL="No">
            <TYPE>{xml_escape(collection_type)}</TYPE>
            <FILTER>{filt}</FILTER>
          </COLLECTION>
          <SYSTEM TYPE="Formulae" NAME="{filt}">$AlterID &gt; {int(from_alterid)}</SYSTEM>
        </TDLMESSAGE>
      </TDL>"""
    elif fetch_fields:
        coll_id = "Oti%sFetchColl" % collection_type
        tdl = f"""
      <TDL>
        <TDLMESSAGE>
          <COLLECTION NAME="{coll_id}" ISMODIFY="No" ISFIXED="No" ISINITIALIZE="No" ISOPTION="No" ISINTERNAL="No">
            <TYPE>{xml_escape(collection_type)}</TYPE>
            <FETCH>{xml_escape(fetch_fields)}</FETCH>
          </COLLECTION>
        </TDLMESSAGE>
      </TDL>"""
    return f"""<ENVELOPE>
  <HEADER>
    <VERSION>1</VERSION>
    <TALLYREQUEST>Export</TALLYREQUEST>
    <TYPE>Collection</TYPE>
    <ID>{xml_escape(coll_id)}</ID>
  </HEADER>
  <BODY>
    <DESC>
      <STATICVARIABLES>
        <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
        {company_tag}
      </STATICVARIABLES>{tdl}
    </DESC>
  </BODY>
</ENVELOPE>"""


def build_voucher_export(from_date, to_date, company_name=None):
    """Export vouchers (Day Book) for a date range as XML, for Tally -> Odoo pull."""
    company_tag = (f"<SVCURRENTCOMPANY>{xml_escape(company_name)}</SVCURRENTCOMPANY>"
                   if company_name else "")
    return f"""<ENVELOPE>
  <HEADER>
    <VERSION>1</VERSION>
    <TALLYREQUEST>Export</TALLYREQUEST>
    <TYPE>Data</TYPE>
    <ID>Day Book</ID>
  </HEADER>
  <BODY>
    <DESC>
      <STATICVARIABLES>
        <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
        {company_tag}
        <SVFROMDATE>{format_tally_date(from_date)}</SVFROMDATE>
        <SVTODATE>{format_tally_date(to_date)}</SVTODATE>
      </STATICVARIABLES>
    </DESC>
  </BODY>
</ENVELOPE>"""
