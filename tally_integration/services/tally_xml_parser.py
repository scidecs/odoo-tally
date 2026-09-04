# -*- coding: utf-8 -*-
"""Parser service for Tally XML payloads and collections.

Parses exported Tally XML documents into clean Python dictionary structures for:
- All Master types (Groups, Ledgers, Units, Stock Groups, Stock Items, Cost Centres, Taxes, Godowns)
- All Voucher types (Sales, Purchase, Credit/Debit Notes, Receipts, Payments, Journals, Contras)
"""
import xml.etree.ElementTree as ET
from datetime import datetime
import re


def _clean_text(elem, tag_name, default=""):
    """Find text in child element safely."""
    if elem is None:
        return default
    child = elem.find(tag_name)
    if child is not None and child.text:
        return child.text.strip()
    return default


def _clean_float(elem, tag_name, default=0.0):
    """Find float in child element safely, stripping currency/UoM text."""
    val = _clean_text(elem, tag_name, "")
    if not val:
        return default
    # Extract leading float/negative number
    m = re.search(r"[-+]?\d*\.?\d+", val)
    if m:
        try:
            return float(m.group(0))
        except ValueError:
            return default
    return default


def _parse_tally_date(date_str):
    """Parse Tally YYYYMMDD date string to YYYY-MM-DD."""
    if not date_str:
        return False
    clean = str(date_str).strip()
    if len(clean) == 8 and clean.isdigit():
        return f"{clean[:4]}-{clean[4:6]}-{clean[6:8]}"
    return clean


def parse_tally_xml_root(xml_content):
    """Parse raw XML string into an ElementTree root, sanitizing Tally control entities."""
    if not xml_content or not xml_content.strip():
        return None
    # Sanitize invalid XML control characters & numeric entity codes (e.g. &#4; used by Tally for system records)
    clean_xml = re.sub(r"&#0*([0-8]|1[1-2]|1[4-9]|2[0-9]|3[0-1]);", "", xml_content)
    clean_xml = re.sub(r"&#x0*([0-8BbCcEeFf]|1[0-9A-Fa-f]);", "", clean_xml)
    try:
        return ET.fromstring(clean_xml)
    except Exception:
        # Try stripping leading/trailing junk
        clean_xml = clean_xml.strip()
        idx = clean_xml.find("<ENVELOPE")
        if idx != -1:
            clean_xml = clean_xml[idx:]
        return ET.fromstring(clean_xml)


def parse_currencies_from_xml(root):
    """Parse all <CURRENCY> elements from XML."""
    currencies = []
    for c in root.iter("CURRENCY"):
        name = c.attrib.get("NAME") or _clean_text(c, "NAME")
        if not name:
            continue
        mailing_name = _clean_text(c, "MAILINGNAME") or _clean_text(c, "EXPANDEDSYMBOL") or ""
        orig_name = _clean_text(c, "ORIGINALNAME")

        # In Tally Prime, Indian Rupee symbol is stored as ASCII '?' in legacy codepages.
        if name == "?" or orig_name == "?" or mailing_name.upper() == "INR" or "rupee" in mailing_name.lower():
            symbol = "₹"
            mailing_name = "INR"
            name = "INR"
        else:
            symbol = orig_name or name
            if symbol == "?":
                symbol = mailing_name or name

        dec_symbol = _clean_text(c, "DECIMALSYMBOL", "paise")
        dec_places = int(_clean_float(c, "DECIMALPLACES", 2.0))
        guid = _clean_text(c, "GUID")
        alterid = _clean_text(c, "ALTERID")
        currencies.append({
            "name": name,
            "formal_name": mailing_name or ("INR" if symbol == "₹" else name),
            "symbol": symbol,
            "decimal_symbol": dec_symbol,
            "decimal_places": dec_places,
            "guid": guid,
            "alterid": alterid,
        })
    return currencies


def parse_groups_from_xml(root):
    """Parse all <GROUP> elements from XML."""
    groups = []
    for g in root.iter("GROUP"):
        name = g.attrib.get("NAME") or _clean_text(g, "NAME")
        if not name:
            continue
        groups.append({
            "name": name,
            "parent": _clean_text(g, "PARENT", "Primary"),
            "nature": _clean_text(g, "NATUREOFGROUP", ""),
            "guid": _clean_text(g, "GUID"),
            "alterid": _clean_text(g, "ALTERID"),
        })
    return groups


def parse_ledgers_from_xml(root):
    """Parse all <LEDGER> elements from XML (both general accounts and parties)."""
    ledgers = []
    for l in root.iter("LEDGER"):
        name = l.attrib.get("NAME") or _clean_text(l, "NAME")
        if not name:
            continue

        parent = _clean_text(l, "PARENT", "")
        # Collect addresses
        addresses = []
        for addr in l.iter("ADDRESS"):
            if addr.text and addr.text.strip():
                addresses.append(addr.text.strip())

        gstin = _clean_text(l, "PARTYGSTIN", "") or _clean_text(l, "GSTIN", "")
        pan = (_clean_text(l, "INCOMETAXNUMBER", "") or _clean_text(l, "PANNUMBER", "")
               or _clean_text(l, "PAN", ""))

        ledgers.append({
            "name": name,
            "parent": parent,
            "guid": _clean_text(l, "GUID"),
            "alterid": _clean_text(l, "ALTERID"),
            "opening_balance": _clean_float(l, "OPENINGBALANCE", 0.0),
            "gstin": gstin,
            "pan": pan,
            "state": _clean_text(l, "STATENAME", "") or _clean_text(l, "STATE", ""),
            "country": _clean_text(l, "COUNTRYNAME", "India"),
            "pincode": _clean_text(l, "PINCODE", ""),
            "email": _clean_text(l, "EMAIL", ""),
            "phone": _clean_text(l, "LEDGERPHONE", "") or _clean_text(l, "LEDGERMOBILE", ""),
            "credit_limit": _clean_float(l, "CREDITLIMIT", 0.0),
            "addresses": addresses,
            "gst_registration_type": _clean_text(l, "GSTREGISTRATIONTYPE", ""),
            "tax_type": _clean_text(l, "TAXTYPE", ""),
            "gst_duty_head": _clean_text(l, "GSTDUTYHEAD", ""),
            "rate_of_tax": _clean_float(l, "RATEOFTAXCALCULATION", 0.0),
            "is_billwise": _clean_text(l, "ISBILLWISEON", "No").lower() in ("yes", "true", "1"),
            "is_tds_applicable": _clean_text(l, "ISTDSAPPLICABLE", "No").lower() in ("yes", "true", "1"),
            "is_tcs_applicable": _clean_text(l, "ISTCSAPPLICABLE", "No").lower() in ("yes", "true", "1"),
            "tds_section": _clean_text(l, "TDSSECTION", ""),
            "tcs_section": _clean_text(l, "TCSSECTION", ""),
        })
    return ledgers


def parse_units_from_xml(root):
    """Parse all <UNIT> elements from XML."""
    units = []
    for u in root.iter("UNIT"):
        name = u.attrib.get("NAME") or _clean_text(u, "NAME")
        if not name:
            continue
        units.append({
            "name": name,
            "formal_name": _clean_text(u, "ORIGINALNAME", name),
            "decimal_places": int(_clean_float(u, "DECIMALPLACES", 0)),
            "uqc": _clean_text(u, "GSTREPUOM", ""),
            "guid": _clean_text(u, "GUID"),
            "alterid": _clean_text(u, "ALTERID"),
        })
    return units


def parse_stock_groups_from_xml(root):
    """Parse all <STOCKGROUP> elements from XML."""
    groups = []
    for group in root.iter("STOCKGROUP"):
        name = group.attrib.get("NAME") or _clean_text(group, "NAME")
        if name:
            groups.append({
                "name": name,
                "parent": _clean_text(group, "PARENT", "Primary"),
                "guid": _clean_text(group, "GUID"),
                "alterid": _clean_text(group, "ALTERID"),
            })
    return groups


def filter_ledgers_for_entity(records, entity):
    """Split Tally's single Ledger collection into parties, taxes, and accounts."""
    result = []
    for record in records or []:
        parent = (record.get("parent") or "").lower()
        taxish = bool(record.get("tax_type") or record.get("gst_duty_head")
                      or any(k in parent for k in ("duties", "tax", "tds", "tcs")))
        party = any(k in parent for k in (
            "sundry debt", "sundry credit", "customer", "vendor", "supplier"))
        if entity == "tax" and taxish:
            result.append(record)
        elif entity == "ledger" and party and not taxish:
            result.append(record)
        elif entity == "opening_balance" and not taxish:
            # Opening balances apply to both party and general ledgers.  The
            # ledger/account_ledger streams remain split to avoid creating
            # banks and income accounts as contacts.
            result.append(record)
        elif entity == "account_ledger" and not party and not taxish:
            result.append(record)
    return result


def parse_stock_items_from_xml(root):
    """Parse all <STOCKITEM> elements from XML with full inventory, rate, barcode, and batch/godown data."""
    items = []
    for s in root.iter("STOCKITEM"):
        name = s.attrib.get("NAME") or _clean_text(s, "NAME")
        if not name:
            continue

        op_qty = _clean_float(s, "OPENINGBALANCE", 0.0)
        cl_qty = _clean_float(s, "CLOSINGBALANCE", 0.0)
        op_rate = _clean_float(s, "OPENINGRATE", 0.0)
        cl_rate = _clean_float(s, "CLOSINGRATE", 0.0)
        op_val = abs(_clean_float(s, "OPENINGVALUE", 0.0))
        cl_val = abs(_clean_float(s, "CLOSINGVALUE", 0.0))

        rate = cl_rate or op_rate
        if not rate and op_qty and op_val:
            rate = op_val / op_qty
        elif not rate and cl_qty and cl_val:
            rate = cl_val / cl_qty

        on_hand_qty = cl_qty if cl_qty != 0.0 else op_qty

        barcode = _clean_text(s, "BARCODE") or _clean_text(s, "PARTNO") or _clean_text(s, "MAILINGNAME")
        if barcode == name:
            barcode = ""

        batch_allocations = []
        for batch in s.iter("BATCHALLOCATIONS.LIST"):
            godown = _clean_text(batch, "GODOWNNAME", "")
            b_name = _clean_text(batch, "BATCHNAME", "")
            b_qty = _clean_float(batch, "CLOSINGBALANCE", 0.0) or _clean_float(batch, "OPENINGBALANCE", 0.0) or _clean_float(batch, "ACTUALQTY", 0.0)
            b_amt = abs(_clean_float(batch, "AMOUNT", 0.0))
            if godown or b_qty:
                batch_allocations.append({
                    "godown": godown or "Main Location",
                    "batch": b_name,
                    "qty": b_qty,
                    "amount": b_amt,
                })

        items.append({
            "name": name,
            "parent_group": _clean_text(s, "PARENT", "Primary"),
            "base_uom": _clean_text(s, "BASEUNITS", "Nos"),
            "hsn_code": _clean_text(s, "HSNCODE", "") or _clean_text(s, "HSNDESCRIPTION", ""),
            "barcode": barcode,
            "description": _clean_text(s, "DESCRIPTION", ""),
            "opening_balance": op_qty,
            "closing_balance": cl_qty,
            "quantity": on_hand_qty,
            "rate": rate,
            "opening_value": op_val,
            "closing_value": cl_val,
            "batch_allocations": batch_allocations,
            "guid": _clean_text(s, "GUID"),
            "alterid": _clean_text(s, "ALTERID"),
        })
    return items



def parse_cost_centres_from_xml(root):
    """Parse all <COSTCENTRE> elements from XML."""
    centres = []
    for c in root.iter("COSTCENTRE"):
        name = c.attrib.get("NAME") or _clean_text(c, "NAME")
        if not name:
            continue
        centres.append({
            "name": name,
            "parent": _clean_text(c, "PARENT", ""),
            "category": _clean_text(c, "CATEGORYNAME", "Primary Cost Category"),
            "guid": _clean_text(c, "GUID"),
            "alterid": _clean_text(c, "ALTERID"),
        })
    return centres


def parse_godowns_from_xml(root):
    """Parse all <GODOWN> elements from XML."""
    godowns = []
    for g in root.iter("GODOWN"):
        name = g.attrib.get("NAME") or _clean_text(g, "NAME")
        if not name:
            continue
        godowns.append({
            "name": name,
            "parent": _clean_text(g, "PARENT", "Primary"),
            "guid": _clean_text(g, "GUID"),
            "alterid": _clean_text(g, "ALTERID"),
        })
    return godowns


def _parse_single_voucher_element(v):
    """Parse a single <VOUCHER> ElementTree element into a dictionary."""
    vch_type = v.attrib.get("VCHTYPE") or _clean_text(v, "VOUCHERTYPENAME")
    vch_num = _clean_text(v, "VOUCHERNUMBER")
    date = _parse_tally_date(_clean_text(v, "DATE"))
    guid = _clean_text(v, "GUID")
    alterid = _clean_text(v, "ALTERID")
    party = _clean_text(v, "PARTYLEDGERNAME") or _clean_text(v, "PARTYNAME")
    narration = _clean_text(v, "NARRATION")
    reference = _clean_text(v, "REFERENCE")

    # Parse Ledger Entries
    ledger_entries = []
    for le in v.findall(".//ALLLEDGERENTRIES.LIST"):
        led_name = _clean_text(le, "LEDGERNAME")
        if not led_name:
            continue
        amt = _clean_float(le, "AMOUNT", 0.0)

        # Bill Allocations
        bill_allocs = []
        for ba in le.findall(".//BILLALLOCATIONS.LIST"):
            bill_allocs.append({
                "name": _clean_text(ba, "NAME"),
                "type": _clean_text(ba, "BILLTYPE", "Agst Ref"),
                "amount": _clean_float(ba, "AMOUNT", 0.0),
            })

        # Cost Centre Allocations
        cc_allocs = []
        for ca in le.findall(".//COSTCENTREALLOCATIONS.LIST"):
            cc_allocs.append({
                "name": _clean_text(ca, "NAME"),
                "amount": _clean_float(ca, "AMOUNT", 0.0),
            })

        ledger_entries.append({
            "ledger": led_name,
            "amount": amt,
            "bill_allocations": bill_allocs,
            "cost_centres": cc_allocs,
        })

    # Parse Inventory Entries
    inventory_entries = []
    for ie in v.findall(".//ALLINVENTORYENTRIES.LIST"):
        item_name = _clean_text(ie, "STOCKITEMNAME")
        if not item_name:
            continue
        amt = _clean_float(ie, "AMOUNT", 0.0)
        qty = _clean_float(ie, "ACTUALQTY", 0.0) or _clean_float(ie, "BILLEDQTY", 0.0)
        rate = _clean_float(ie, "RATE", 0.0)
        disc = _clean_float(ie, "DISCOUNT", 0.0)
        gst_rate = (
            _clean_float(ie, "GSTRATE", 0.0)
            or _clean_float(ie, "GSTPERCENTAGE", 0.0)
            or _clean_float(ie, "BASICRATEOFINVOICETAX", 0.0)
        )
        if not gst_rate:
            for rate_node in ie.findall(".//RATEDETAILS.LIST") + ie.findall(".//GSTRATEDETAILS.LIST"):
                gst_rate = (_clean_float(rate_node, "GSTRATE", 0.0)
                            or _clean_float(rate_node, "GSTPERCENTAGE", 0.0)
                            or _clean_float(rate_node, "GSTRATEVALUATION", 0.0))
                if gst_rate:
                    break

        # Godown
        godown = _clean_text(ie.find(".//BATCHALLOCATIONS.LIST"), "GODOWNNAME", "Main Location") if ie.find(".//BATCHALLOCATIONS.LIST") is not None else "Main Location"

        inventory_entries.append({
            "item": item_name,
            "qty": qty,
            "rate": rate,
            "amount": amt,
            "discount": disc,
            "gst_rate": gst_rate,
            "godown": godown,
        })

    # E-Way Bill details
    eway_elem = v.find(".//EWAYBILLDETAILS.LIST")
    if eway_elem is None:
        eway_elem = v.find(".//EWAYBILLDETAILS")
    eway_bill_no = _clean_text(eway_elem, "EWAYBILLNO") if eway_elem is not None else _clean_text(v, "EWAYBILLNO")
    eway_bill_date = _parse_tally_date(_clean_text(eway_elem, "EWAYBILLDATE") if eway_elem is not None else "")
    vehicle_no = _clean_text(eway_elem, "VEHICLENO") if eway_elem is not None else _clean_text(v, "VEHICLENO")
    distance = _clean_float(eway_elem, "TRANSPORTDISTANCE") if eway_elem is not None else _clean_float(v, "TRANSPORTDISTANCE")
    transporter_name = _clean_text(eway_elem, "TRANSPORTERNAME") if eway_elem is not None else _clean_text(v, "TRANSPORTERNAME")
    transporter_id = _clean_text(eway_elem, "TRANSPORTERID") if eway_elem is not None else _clean_text(v, "TRANSPORTERID")

    # E-Invoice / IRN details
    irn_elem = v.find(".//IRNDETAILS.LIST")
    if irn_elem is None:
        irn_elem = v.find(".//IRNDETAILS")
    irn = _clean_text(irn_elem, "IRN") if irn_elem is not None else _clean_text(v, "IRN")
    ack_no = _clean_text(irn_elem, "ACKNO") if irn_elem is not None else _clean_text(v, "ACKNO")
    ack_date = _clean_text(irn_elem, "ACKDATE") if irn_elem is not None else _clean_text(v, "ACKDATE")
    qrcode = _clean_text(irn_elem, "QRCODE") if irn_elem is not None else _clean_text(v, "SIGNEDQRCODE")

    # State flags
    is_cancelled = _clean_text(v, "ISCANCELLED").lower() in ("yes", "1", "true")
    is_deleted = _clean_text(v, "ISDELETED").lower() in ("yes", "1", "true")
    is_optional = _clean_text(v, "ISOPTIONAL").lower() in ("yes", "1", "true")

    # Bank instrument allocations (cheque / transaction ref)
    bank_elem = v.find(".//BANKALLOCATIONS.LIST")
    cheque_no = _clean_text(bank_elem, "INSTRUMENTNUMBER") if bank_elem is not None else ""
    cheque_date = _clean_text(bank_elem, "INSTRUMENTDATE") if bank_elem is not None else ""

    # Place of supply / State
    place_of_supply = _clean_text(v, "PLACEOFSUPPLY") or _clean_text(v, "STATENAME")

    return {
        "voucher_type": vch_type,
        "voucher_number": vch_num,
        "date": date,
        "guid": guid,
        "alterid": alterid,
        "party_ledger": party,
        "reference": reference,
        "narration": narration,
        "is_cancelled": is_cancelled,
        "is_deleted": is_deleted,
        "is_optional": is_optional,
        "cheque_no": cheque_no,
        "cheque_date": cheque_date,
        "ledger_entries": ledger_entries,
        "inventory_entries": inventory_entries,
        "eway_bill_no": eway_bill_no,
        "eway_bill_date": eway_bill_date,
        "vehicle_no": vehicle_no,
        "distance": distance,
        "transporter_name": transporter_name,
        "transporter_id": transporter_id,
        "irn": irn,
        "ack_no": ack_no,
        "ack_date": ack_date,
        "qrcode": qrcode,
        "place_of_supply": place_of_supply,
    }


def parse_vouchers_from_xml(root):
    """Parse all <VOUCHER> elements from XML root."""
    vouchers = []
    for v in root.iter("VOUCHER"):
        vch = _parse_single_voucher_element(v)
        if vch.get("voucher_type") or vch.get("voucher_number"):
            vouchers.append(vch)
    return vouchers


def iterparse_vouchers_from_xml(xml_stream_or_str):
    """Streaming iterator over <VOUCHER> elements to handle massive Day Book exports with minimal RAM."""
    import io
    if isinstance(xml_stream_or_str, str):
        # Sanitize control characters
        clean_xml = re.sub(r"&#0*([0-8]|1[1-2]|1[4-9]|2[0-9]|3[0-1]);", "", xml_stream_or_str)
        clean_xml = re.sub(r"&#x0*([0-8BbCcEeFf]|1[0-9A-Fa-f]);", "", clean_xml)
        source = io.StringIO(clean_xml)
    else:
        source = xml_stream_or_str

    context = ET.iterparse(source, events=("end",))
    for event, elem in context:
        if elem.tag == "VOUCHER":
            vch = _parse_single_voucher_element(elem)
            elem.clear()
            yield vch
