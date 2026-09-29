# -*- coding: utf-8 -*-
"""Builder service for constructing Tally XML requests and import envelopes.

Builds standard Tally XML messages for:
- Master records (Groups, Ledgers, Parties, UoMs, Stock Items, Cost Centres, Taxes, Godowns)
- Voucher transactions (Sales, Purchase, Credit/Debit Note, Receipts, Payments, Journals, Contras)
- Export / AlterID query requests (TDL Collections)
"""
import html
from datetime import date
from xml.sax.saxutils import escape


def xml_escape(value):
    """Safely escape text for XML elements."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    # Escape quotes as well as & < > so values used inside NAME="..." attributes
    # (e.g. a party named M/s "Sharma" & Sons) cannot break the XML envelope.
    return escape(str(value), {'"': "&quot;", "'": "&apos;"})


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


def normalize_tally_uom(name):
    """Return the canonical Tally unit used by outbound stock masters/vouchers."""
    value = (name or "Nos").strip()
    return "Nos" if value in ("Units", "Unit(s)", "Unit", "Nos") else value


def format_standard_rate_date(value=None):
    """Format a Tally standard cost/price applicability date as YYYYMMDD."""
    if value is None:
        value = date.today()
    if hasattr(value, "strftime"):
        return value.strftime("%Y%m%d")
    clean = str(value).replace("-", "").replace("/", "")[:8]
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


def _master_header(tag, name, old_name=None, guid=None):
    """Open a master element.

    Tally identifies masters by name and ignores the GUID we send (it keeps it
    as REMOTEALTGUID). A rename must therefore address the *current* Tally name
    and carry the new one in NAME.LIST; sending the new name with ACTION=Create
    would create a second master.
    """
    guid_tag = f"<GUID>{xml_escape(guid)}</GUID>" if guid else ""
    if old_name and old_name != name:
        return (f'<{tag} NAME="{xml_escape(old_name)}" ACTION="Alter">\n    {guid_tag}\n'
                f'    <NAME.LIST TYPE="String"><NAME>{xml_escape(name)}</NAME></NAME.LIST>')
    return (f'<{tag} NAME="{xml_escape(name)}" ACTION="Create">\n    {guid_tag}\n'
            f'    <NAME>{xml_escape(name)}</NAME>')


# ==============================================================================
# MASTER XML BUILDERS
# ==============================================================================

def build_group_xml(name, parent=None, nature=None, guid=None, old_name=None):
    """Build <GROUP> XML."""
    guid_tag = f'<GUID>{xml_escape(guid)}</GUID>' if guid else ''
    nature_tag = f'<NATUREOFGROUP>{xml_escape(nature)}</NATUREOFGROUP>' if nature else ''
    parent_tag = f'<PARENT>{xml_escape(parent)}</PARENT>' if parent and parent != 'Primary' else '<PARENT/>'
    return f"""<TALLYMESSAGE xmlns:UDF="TallyUDF">
  {_master_header('GROUP', name, old_name, guid)}
    {parent_tag}
    <ISSUBLEDGER>No</ISSUBLEDGER>
    <ISBILLWISEON>No</ISBILLWISEON>
    <ISCOSTCENTRESON>No</ISCOSTCENTRESON>
    {nature_tag}
  </GROUP>
</TALLYMESSAGE>"""


def build_account_ledger_xml(name, parent="Indirect Expenses", opening_balance=0.0,
                             is_billwise=False, currency="INR", description=None, guid=None,
                             affects_stock=False, old_name=None):
    """Build General Account <LEDGER> XML."""
    guid_tag = f'<GUID>{xml_escape(guid)}</GUID>' if guid else ''
    op_bal_tag = f'<OPENINGBALANCE>{float(opening_balance or 0.0):.2f}</OPENINGBALANCE>' if opening_balance else ''
    desc_tag = f'<DESCRIPTION>{xml_escape(description)}</DESCRIPTION>' if description else ''
    # Only foreign-currency ledgers name a currency; the base currency's Tally
    # name varies by install (often the rupee symbol), so it is never forced.
    currency_tag = (f'<CURRENCYNAME>{xml_escape(currency)}</CURRENCYNAME>'
                    if currency and currency not in ('INR', '₹') else '')
    return f"""<TALLYMESSAGE xmlns:UDF="TallyUDF">
  {_master_header('LEDGER', name, old_name, guid)}
    <PARENT>{xml_escape(parent or 'Indirect Expenses')}</PARENT>
    <ISBILLWISEON>{'Yes' if is_billwise else 'No'}</ISBILLWISEON>
    <ISCOSTCENTRESON>No</ISCOSTCENTRESON>
    <AFFECTSSTOCK>{'Yes' if affects_stock else 'No'}</AFFECTSSTOCK>
    {currency_tag}
    {op_bal_tag}
    {desc_tag}
  </LEDGER>
</TALLYMESSAGE>"""


def build_party_ledger_xml(name, parent="Sundry Debtors", gstin=None, pan=None,
                           address_lines=None, state_name=None, country_name="India",
                           pincode=None, email=None, phone=None, credit_limit=0.0,
                           opening_balance=0.0, guid=None, old_name=None):
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
  {_master_header('LEDGER', name, old_name, guid)}
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


def build_stock_group_xml(name, parent=None, guid=None, old_name=None):
    """Build <STOCKGROUP> XML."""
    guid_tag = f'<GUID>{xml_escape(guid)}</GUID>' if guid else ''
    parent_tag = f'<PARENT>{xml_escape(parent)}</PARENT>' if parent and parent != 'Primary' else '<PARENT/>'
    return f"""<TALLYMESSAGE xmlns:UDF="TallyUDF">
  {_master_header('STOCKGROUP', name, old_name, guid)}
    {parent_tag}
    <ISADDABLE>Yes</ISADDABLE>
  </STOCKGROUP>
</TALLYMESSAGE>"""


def build_stock_item_xml(name, base_uom="Nos", parent_group="Primary", hsn_code=None,
                         gst_rate=0.0, standard_cost=0.0, sale_price=0.0,
                         opening_qty=0.0, opening_rate=0.0, guid=None,
                         part_no=None, barcode=None, effective_date=None,
                         action="Create", old_name=None):
    """Build <STOCKITEM> XML."""
    if action not in ("Create", "Alter"):
        raise ValueError("Stock item action must be Create or Alter")
    guid_tag = f'<GUID>{xml_escape(guid)}</GUID>' if guid else ''
    hsn_tag = f'<HSNCODE>{xml_escape(hsn_code)}</HSNCODE>' if hsn_code else ''
    gst_tag = f'<GSTRATEDETAILS.LIST><GSTRATE>{float(gst_rate or 0.0):.2f}</GSTRATE></GSTRATEDETAILS.LIST>' if gst_rate else ''
    rate_date = format_standard_rate_date(effective_date)
    cost_tag = (f'<STANDARDCOSTLIST.LIST><DATE>{rate_date}</DATE>'
                f'<RATE>{float(standard_cost or 0.0):.2f}</RATE>'
                f'</STANDARDCOSTLIST.LIST>') if standard_cost else ''
    price_tag = (f'<STANDARDPRICELIST.LIST><DATE>{rate_date}</DATE>'
                 f'<RATE>{float(sale_price or 0.0):.2f}</RATE>'
                 f'</STANDARDPRICELIST.LIST>') if sale_price else ''
    part_tag = (f'<MAILINGNAME.LIST TYPE="String"><MAILINGNAME>'
                f'{xml_escape(part_no)}</MAILINGNAME></MAILINGNAME.LIST>') if part_no else ''
    barcode_tag = f'<BARCODE>{xml_escape(barcode)}</BARCODE>' if barcode else ''

    op_val = float(opening_qty or 0) * float(opening_rate or 0)
    op_xml = f"""<OPENINGBALANCE>{float(opening_qty):.2f} {xml_escape(base_uom)}</OPENINGBALANCE>
    <OPENINGRATE>{float(opening_rate):.2f}</OPENINGRATE>
    <OPENINGVALUE>-{op_val:.2f}</OPENINGVALUE>""" if opening_qty else ""

    parent_tag = f"<PARENT>{xml_escape(parent_group)}</PARENT>" if parent_group and parent_group != "Primary" else "<PARENT/>"
    if old_name and old_name != name:
        _stock_item_header = _master_header("STOCKITEM", name, old_name, guid)
    else:
        _stock_item_header = (f'<STOCKITEM NAME="{xml_escape(name)}" ACTION="{action}">\n    {guid_tag}\n'
                              f'    <NAME>{xml_escape(name)}</NAME>')

    return f"""<TALLYMESSAGE xmlns:UDF="TallyUDF">
  {_stock_item_header}
    {parent_tag}
    <BASEUNITS>{xml_escape(base_uom or 'Nos')}</BASEUNITS>
    {part_tag}
    {barcode_tag}
    {hsn_tag}
    {gst_tag}
    {cost_tag}
    {price_tag}
    {op_xml}
  </STOCKITEM>
</TALLYMESSAGE>"""


def build_cost_centre_xml(name, parent=None, category="Primary Cost Category", guid=None, old_name=None):
    """Build <COSTCENTRE> XML."""
    guid_tag = f'<GUID>{xml_escape(guid)}</GUID>' if guid else ''
    parent_tag = f'<PARENT>{xml_escape(parent)}</PARENT>' if parent else ''
    return f"""<TALLYMESSAGE xmlns:UDF="TallyUDF">
  {_master_header('COSTCENTRE', name, old_name, guid)}
    <CATEGORYNAME>{xml_escape(category or 'Primary Cost Category')}</CATEGORYNAME>
    {parent_tag}
  </COSTCENTRE>
</TALLYMESSAGE>"""


def build_godown_xml(name, parent=None, guid=None, old_name=None):
    """Build <GODOWN> XML."""
    guid_tag = f'<GUID>{xml_escape(guid)}</GUID>' if guid else ''
    parent_tag = f'<PARENT>{xml_escape(parent)}</PARENT>' if parent and parent not in ('Primary', 'Main Location') else '<PARENT/>'
    return f"""<TALLYMESSAGE xmlns:UDF="TallyUDF">
  {_master_header('GODOWN', name, old_name, guid)}
    {parent_tag}
  </GODOWN>
</TALLYMESSAGE>"""


def build_tax_ledger_xml(name, gst_type="CGST", rate=0.0, parent="Duties & Taxes", guid=None, old_name=None):
    """Build Tax <LEDGER> XML for GST (CGST, SGST, IGST, Cess)."""
    guid_tag = f'<GUID>{xml_escape(guid)}</GUID>' if guid else ''
    return f"""<TALLYMESSAGE xmlns:UDF="TallyUDF">
  {_master_header('LEDGER', name, old_name, guid)}
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
                      narration=None, guid=None, reference=None, is_invoice=True,
                      educational_mode=False, alter_address=None):
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
    date_str = format_tally_date(date, educational_mode=educational_mode)
    ref_tag = f'<REFERENCE>{xml_escape(reference)}</REFERENCE>' if reference else ''
    narration_tag = f'<NARRATION>{xml_escape(narration)}</NARRATION>' if narration else ''

    # Build Inventory entries
    inv_xml = []
    if inventory_entries:
        for inv in inventory_entries:
            item_name = inv.get("item", "")
            qty = float(inv.get("qty", 0.0))
            uom = normalize_tally_uom(inv.get("uom", "Nos"))
            rate = float(inv.get("rate", 0.0))
            amount = float(inv.get("amount", 0.0))
            godown = inv.get("godown", "Main Location")
            disc = float(inv.get("discount", 0.0))
            disc_tag = f"<DISCOUNT>{disc:.2f}</DISCOUNT>" if disc else ""

            batch_xml = f"""<BATCHALLOCATIONS.LIST>
            <GODOWNNAME>{xml_escape(godown)}</GODOWNNAME>
            <BATCHNAME>Primary Batch</BATCHNAME>
            <DESTINATIONGODOWNNAME>{xml_escape(godown)}</DESTINATIONGODOWNNAME>
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

            # Tally names Stock Journal consumption/source rows "IN" and
            # production/destination rows "OUT". Its own export uses a
            # negative amount in IN and a positive amount in OUT.
            inventory_tag = ("INVENTORYENTRIESIN.LIST" if amount < 0
                             else "INVENTORYENTRIESOUT.LIST") if voucher_type == "Stock Journal" else "ALLINVENTORYENTRIES.LIST"
            inv_xml.append(f"""        <{inventory_tag}>
          <STOCKITEMNAME>{xml_escape(item_name)}</STOCKITEMNAME>
          <ISDEEMEDPOSITIVE>{'Yes' if amount < 0 else 'No'}</ISDEEMEDPOSITIVE>
          <RATE>{rate:.2f}/{xml_escape(uom)}</RATE>
          <AMOUNT>{amount:.2f}</AMOUNT>
          <ACTUALQTY>{qty:.2f} {xml_escape(uom)}</ACTUALQTY>
          <BILLEDQTY>{qty:.2f} {xml_escape(uom)}</BILLEDQTY>
          {disc_tag}
          {batch_xml}{acc_alloc_xml}
        </{inventory_tag}>""")

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

            ledger_tag = "LEDGERENTRIES.LIST" if is_invoice else "ALLLEDGERENTRIES.LIST"
            led_xml.append(f"""        <{ledger_tag}>
          <LEDGERNAME>{xml_escape(led_name)}</LEDGERNAME>
          <ISDEEMEDPOSITIVE>{is_deemed_positive}</ISDEEMEDPOSITIVE>
          <ISPARTYLEDGER>{'Yes' if led.get('bill_allocations') else 'No'}</ISPARTYLEDGER>
          <ISLASTDEEMEDPOSITIVE>{is_deemed_positive}</ISLASTDEEMEDPOSITIVE>
          <AMOUNT>{amount:.2f}</AMOUNT>
{bill_alloc_str}
{cc_alloc_str}
        </{ledger_tag}>""")

    led_entries_str = "\n".join(led_xml)

    persisted_view = ("Consumption Voucher View" if voucher_type == "Stock Journal"
                      else "Invoice Voucher View" if is_invoice
                      else "Accounting Voucher View")
    if alter_address and alter_address.get("voucher_number"):
        # A voucher Tally already holds (created by Odoo or typed in Tally) is
        # addressed by its Tally date, type and number; REMOTEID only matches
        # vouchers Odoo created, and Tally ignores the GUID we send.
        old_date = alter_address.get("date") or date
        old_day = (old_date.strftime("%d-%b-%Y") if hasattr(old_date, "strftime")
                   else format_tally_date(old_date))
        voucher_open = (f'<VOUCHER DATE="{xml_escape(old_day)}" TAGNAME="Voucher Number" '
                        f'TAGVALUE="{xml_escape(alter_address["voucher_number"])}" '
                        f'VCHTYPE="{xml_escape(alter_address.get("voucher_type") or voucher_type)}" '
                        f'ACTION="Alter" OBJVIEW="{persisted_view}">')
        voucher_number = alter_address["voucher_number"]
    else:
        remote = (' REMOTEID="' + xml_escape(guid) + '"') if guid else ''
        voucher_open = f'<VOUCHER VCHTYPE="{xml_escape(voucher_type)}" ACTION="Create" OBJVIEW="{persisted_view}"{remote}>'
    return f"""<TALLYMESSAGE xmlns:UDF="TallyUDF">
  {voucher_open}
    {guid_tag}
    {f'<REMOTEID>{xml_escape(guid)}</REMOTEID>' if guid else ''}
    <DATE>{date_str}</DATE>
    <EFFECTIVEDATE>{date_str}</EFFECTIVEDATE>
    <VOUCHERTYPENAME>{xml_escape(voucher_type)}</VOUCHERTYPENAME>
    <VOUCHERNUMBER>{xml_escape(voucher_number)}</VOUCHERNUMBER>
    <PARTYLEDGERNAME>{xml_escape(party_ledger)}</PARTYLEDGERNAME>
    <PERSISTEDVIEW>{persisted_view}</PERSISTEDVIEW>
    <ISINVOICE>{'Yes' if is_invoice else 'No'}</ISINVOICE>
    <OBJVIEW>{persisted_view}</OBJVIEW>
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
# EXPORT REQUESTS
# ==============================================================================

IDENTITY_FETCH = "GUID,AlterID,MasterID,RemoteAltGUID"

# A bare collection export returns only NAME and PARENT; identity (GUID,
# AlterID, MasterID, RemoteAltGUID) and business fields must be fetched
# explicitly or delta sync, identity mapping and reconciliation cannot work.
DEFAULT_FETCH = {
    "Company": "Name",
    "Currency": "Name,MailingName,OriginalName,ExpandedSymbol,DecimalSymbol,DecimalPlaces," + IDENTITY_FETCH,
    "Group": "Name,Parent,ReservedName,NatureOfGroup,IsRevenue,AffectsGrossProfit," + IDENTITY_FETCH,
    "Ledger": ("Name,Parent,OpeningBalance,ClosingBalance,PartyGSTIN,GSTRegistrationType,IncomeTaxNumber,"
               "LedStateName,StateName,OldLedStateName,CountryName,CountryOfResidence,Pincode,Email,"
               "LedgerPhone,LedgerMobile,CreditLimit,Address,TaxType,GSTDutyHead,RateOfTaxCalculation,"
               "IsBillWiseOn,CurrencyName,LedGSTRegDetails,LedMailingDetails," + IDENTITY_FETCH),
    "Unit": "Name,OriginalName,DecimalPlaces,GSTRepUOM,IsSimpleUnit," + IDENTITY_FETCH,
    "StockGroup": "Name,Parent," + IDENTITY_FETCH,
    "StockItem": ("Name,Parent,BaseUnits,MailingName,PartNo,Barcode,HSNCode,HSNDescription,Description,"
                  "StandardCost,StandardPrice,OpeningBalance,OpeningValue,OpeningRate,ClosingBalance,"
                  "ClosingValue,ClosingRate,BatchAllocations," + IDENTITY_FETCH),
    "CostCentre": "Name,Parent,CategoryName," + IDENTITY_FETCH,
    "Godown": "Name,Parent," + IDENTITY_FETCH,
}

VOUCHER_FETCH = (
    "Date,VoucherTypeName,VoucherNumber,Reference,ReferenceDate,Narration,PartyLedgerName,PartyName,"
    "IsCancelled,IsDeleted,IsOptional,IsInvoice,PersistedView,PlaceOfSupply,StateName,"
    "AllLedgerEntries,LedgerEntries,AllInventoryEntries,InventoryEntries,InventoryEntriesIn,"
    "InventoryEntriesOut,EWayBillDetails,IRNDetails," + IDENTITY_FETCH)

# entity -> native Tally collection object name
COLLECTION_MAP = {
    "currency": "Currency",
    "group": "Group",
    "account_ledger": "Ledger",
    "ledger": "Ledger",
    "uom": "Unit",
    "stock_group": "StockGroup",
    "stock_item": "StockItem",
    "cost_centre": "CostCentre",
    "godown": "Godown",
    "tax": "Ledger",
    "opening_balance": "Ledger",
}


def tdl_string(value):
    """Quote a literal for a TDL formula (double quotes are doubled)."""
    return '"%s"' % str(value or "").replace('"', '""')


def tdl_date(value):
    """TDL date literal, e.g. ``$$Date:"01-09-2026"``."""
    if hasattr(value, "strftime"):
        value = value.strftime("%d-%m-%Y")
    return '$$Date:"%s"' % value


def _collection_request(coll_id, collection_type, company_name=None, fetch=None, formula=None):
    company_tag = (f"<SVCURRENTCOMPANY>{xml_escape(company_name)}</SVCURRENTCOMPANY>"
                   if company_name else "")
    filter_tag = "<FILTER>OtiFilter</FILTER>" if formula else ""
    system = (f'<SYSTEM TYPE="Formulae" NAME="OtiFilter">{xml_escape(formula)}</SYSTEM>'
              if formula else "")
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
      </STATICVARIABLES>
      <TDL>
        <TDLMESSAGE>
          <COLLECTION NAME="{xml_escape(coll_id)}" ISMODIFY="No" ISFIXED="No" ISINITIALIZE="No" ISOPTION="No" ISINTERNAL="No">
            <TYPE>{xml_escape(collection_type)}</TYPE>
            <FETCH>{xml_escape(fetch or "Name")}</FETCH>
            {filter_tag}
          </COLLECTION>
          {system}
        </TDLMESSAGE>
      </TDL>
    </DESC>
  </BODY>
</ENVELOPE>"""


def build_collection_export(collection_type, company_name=None, from_alterid=None,
                            fetch_fields=None, formula=None):
    """Export a native master collection with identity + business fields.

    ``from_alterid`` adds a server-side ``$AlterID > n`` filter; ``formula`` adds
    any further TDL condition. Both combine with the field list.
    """
    conditions = []
    if from_alterid and int(from_alterid) > 0:
        conditions.append("$AlterID > %d" % int(from_alterid))
    if formula:
        conditions.append("(%s)" % formula)
    fetch = fetch_fields or DEFAULT_FETCH.get(collection_type, "Name,Parent," + IDENTITY_FETCH)
    if "GUID" not in fetch.upper():
        fetch = fetch + "," + IDENTITY_FETCH
    return _collection_request("Oti%sColl" % collection_type, collection_type, company_name,
                               fetch=fetch, formula=" AND ".join(conditions) or None)


def build_voucher_collection_export(company_name=None, from_alterid=None, from_date=None,
                                    to_date=None, formula=None, fetch_fields=None):
    """Export vouchers across any dates, filtered by AlterID and/or date range.

    The Day Book report only honours Tally's *current* date, so a date-range
    Day Book silently misses back-dated entries and edits to older vouchers.
    """
    conditions = []
    if from_alterid and int(from_alterid) > 0:
        conditions.append("$AlterID > %d" % int(from_alterid))
    if from_date:
        conditions.append("$Date >= %s" % tdl_date(from_date))
    if to_date:
        conditions.append("$Date <= %s" % tdl_date(to_date))
    if formula:
        conditions.append("(%s)" % formula)
    return _collection_request("OtiVoucherColl", "Voucher", company_name,
                               fetch=fetch_fields or VOUCHER_FETCH,
                               formula=" AND ".join(conditions) or None)


def build_identity_lookup(collection_type, remote_alt_guids=None, names=None, company_name=None,
                          master_ids=None):
    """Find Tally objects created from Odoo by the GUID we sent (REMOTEALTGUID),
    by name, or by MasterID, returning their real Tally identity."""
    terms = ["$RemoteAltGUID = %s" % tdl_string(g) for g in (remote_alt_guids or []) if g]
    terms += ["$Name = %s" % tdl_string(n) for n in (names or []) if n]
    terms += ["$MasterID = %d" % int(m) for m in (master_ids or []) if str(m).strip().isdigit()]
    if not terms:
        raise ValueError("Identity lookup needs at least one GUID, name or MasterID.")
    fetch = "Name,Parent," + IDENTITY_FETCH
    if collection_type == "Voucher":
        fetch = "Date,VoucherTypeName,VoucherNumber,Reference," + IDENTITY_FETCH
    return _collection_request("OtiIdentity", collection_type, company_name, fetch=fetch,
                               formula=" OR ".join(terms))


def build_voucher_cancel_xml(voucher_type, voucher_number, date, narration=None, remote_id=None):
    """Cancel a voucher in Tally (keeps it numbered, zero value, ISCANCELLED).

    Tally addresses the voucher by date, type and number. An element with an
    empty body crashed TallyPrime during testing, so a narration is always sent.
    """
    day = date.strftime("%d-%b-%Y") if hasattr(date, "strftime") else str(date)
    if len(day) == 8 and day.isdigit():
        day = "%s-%s-%s" % (day[6:8], ("Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec")[int(day[4:6]) - 1], day[:4])
    if remote_id:
        # Vouchers created by Odoo are addressed by the REMOTEID Tally stored:
        # unambiguous, unlike voucher numbers which repeat across voucher types.
        return f"""<TALLYMESSAGE xmlns:UDF="TallyUDF">
  <VOUCHER REMOTEID="{xml_escape(remote_id)}" VCHTYPE="{xml_escape(voucher_type)}" ACTION="Cancel">
    <NARRATION>{xml_escape(narration or "Cancelled from Odoo")}</NARRATION>
  </VOUCHER>
</TALLYMESSAGE>"""
    return f"""<TALLYMESSAGE xmlns:UDF="TallyUDF">
  <VOUCHER DATE="{xml_escape(day)}" TAGNAME="Voucher Number" TAGVALUE="{xml_escape(voucher_number)}" VCHTYPE="{xml_escape(voucher_type)}" ACTION="Cancel">
    <NARRATION>{xml_escape(narration or "Cancelled from Odoo")}</NARRATION>
  </VOUCHER>
</TALLYMESSAGE>"""
