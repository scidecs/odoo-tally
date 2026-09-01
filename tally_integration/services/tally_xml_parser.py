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
    """Parse raw XML string into an ElementTree root."""
    if not xml_content or not xml_content.strip():
        return None
    try:
        return ET.fromstring(xml_content)
    except Exception as e:
        # Try stripping leading/trailing junk
        clean_xml = xml_content.strip()
        idx = clean_xml.find("<ENVELOPE")
        if idx != -1:
            clean_xml = clean_xml[idx:]
        return ET.fromstring(clean_xml)


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

        ledgers.append({
            "name": name,
            "parent": parent,
            "guid": _clean_text(l, "GUID"),
            "alterid": _clean_text(l, "ALTERID"),
            "opening_balance": _clean_float(l, "OPENINGBALANCE", 0.0),
            "gstin": _clean_text(l, "PARTYGSTIN", ""),
            "pan": _clean_text(l, "INCOMETAXNUMBER", ""),
            "state": _clean_text(l, "STATENAME", ""),
            "country": _clean_text(l, "COUNTRYNAME", "India"),
            "pincode": _clean_text(l, "PINCODE", ""),
            "email": _clean_text(l, "EMAIL", ""),
            "phone": _clean_text(l, "LEDGERPHONE", "") or _clean_text(l, "LEDGERMOBILE", ""),
            "credit_limit": _clean_float(l, "CREDITLIMIT", 0.0),
            "addresses": addresses,
            "tax_type": _clean_text(l, "TAXTYPE", ""),
            "gst_duty_head": _clean_text(l, "GSTDUTYHEAD", ""),
            "rate_of_tax": _clean_float(l, "RATEOFTAXCALCULATION", 0.0),
            "is_billwise": _clean_text(l, "ISBILLWISEON", "No").lower() in ("yes", "true", "1"),
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


def parse_stock_items_from_xml(root):
    """Parse all <STOCKITEM> elements from XML."""
    items = []
    for s in root.iter("STOCKITEM"):
        name = s.attrib.get("NAME") or _clean_text(s, "NAME")
        if not name:
            continue
        items.append({
            "name": name,
            "parent_group": _clean_text(s, "PARENT", "Primary"),
            "base_uom": _clean_text(s, "BASEUNITS", "Nos"),
            "hsn_code": _clean_text(s, "HSNCODE", "") or _clean_text(s, "HSNDESCRIPTION", ""),
            "opening_balance": _clean_float(s, "OPENINGBALANCE", 0.0),
            "opening_rate": _clean_float(s, "OPENINGRATE", 0.0),
            "opening_value": _clean_float(s, "OPENINGVALUE", 0.0),
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


def parse_vouchers_from_xml(root):
    """Parse all <VOUCHER> elements from XML."""
    vouchers = []
    for v in root.iter("VOUCHER"):
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

            # Godown
            godown = _clean_text(ie.find(".//BATCHALLOCATIONS.LIST"), "GODOWNNAME", "Main Location") if ie.find(".//BATCHALLOCATIONS.LIST") is not None else "Main Location"

            inventory_entries.append({
                "item": item_name,
                "qty": qty,
                "rate": rate,
                "amount": amt,
                "discount": disc,
                "godown": godown,
            })

        vouchers.append({
            "voucher_type": vch_type,
            "voucher_number": vch_num,
            "date": date,
            "guid": guid,
            "alterid": alterid,
            "party_ledger": party,
            "reference": reference,
            "narration": narration,
            "ledger_entries": ledger_entries,
            "inventory_entries": inventory_entries,
        })
    return vouchers
