# -*- coding: utf-8 -*-
"""Unit tests for Tally XML building, parsing, and transform utilities."""
import os
import sys
import unittest

# Add custom-addons to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "tally_integration")))

from services import tally_xml_builder, tally_xml_parser


class TestTallyXMLTransform(unittest.TestCase):

    def test_build_and_parse_party_ledger(self):
        xml_str = tally_xml_builder.build_party_ledger_xml(
            name="Alpha Technologies Pvt Ltd",
            parent="Sundry Debtors",
            gstin="27AAACA1234A1Z5",
            pan="AAACA1234A",
            address_lines=["Plot 42, MIDC Industrial Area", "Andheri East"],
            state_name="Maharashtra",
            country_name="India",
            pincode="400093",
            email="accounts@alphatech.example",
            phone="+919876543210",
            credit_limit=500000.0,
            guid="test-guid-alpha-001"
        )
        self.assertIn("Alpha Technologies Pvt Ltd", xml_str)
        self.assertIn("<PARTYGSTIN>27AAACA1234A1Z5</PARTYGSTIN>", xml_str)
        self.assertIn("<STATENAME>Maharashtra</STATENAME>", xml_str)

        # Parse back
        root = tally_xml_parser.parse_tally_xml_root(xml_str)
        ledgers = tally_xml_parser.parse_ledgers_from_xml(root)
        self.assertEqual(len(ledgers), 1)
        l = ledgers[0]
        self.assertEqual(l["name"], "Alpha Technologies Pvt Ltd")
        self.assertEqual(l["parent"], "Sundry Debtors")
        self.assertEqual(l["gstin"], "27AAACA1234A1Z5")
        self.assertEqual(l["guid"], "test-guid-alpha-001")
        self.assertEqual(l["pincode"], "400093")
        self.assertEqual(len(l["addresses"]), 2)

    def test_build_and_parse_stock_item(self):
        xml_str = tally_xml_builder.build_stock_item_xml(
            name="Laptop Model X1",
            base_uom="Nos",
            parent_group="Electronics",
            hsn_code="84713010",
            gst_rate=18.0,
            standard_cost=45000.0,
            sale_price=60000.0,
            opening_qty=10.0,
            opening_rate=45000.0,
            guid="test-guid-stock-001"
        )
        self.assertIn("Laptop Model X1", xml_str)
        self.assertIn("<HSNCODE>84713010</HSNCODE>", xml_str)

        root = tally_xml_parser.parse_tally_xml_root(xml_str)
        items = tally_xml_parser.parse_stock_items_from_xml(root)
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item["name"], "Laptop Model X1")
        self.assertEqual(item["base_uom"], "Nos")
        self.assertEqual(item["hsn_code"], "84713010")

    def test_build_and_parse_sales_voucher(self):
        ledger_entries = [
            {
                "ledger": "Alpha Technologies Pvt Ltd",
                "amount": 70800.0,
                "bill_allocations": [{"type": "New Ref", "name": "INV-2026-001", "amount": 70800.0}],
            },
            {
                "ledger": "Sales Account",
                "amount": -60000.0,
            },
            {
                "ledger": "Output CGST @ 9%",
                "amount": -5400.0,
            },
            {
                "ledger": "Output SGST @ 9%",
                "amount": -5400.0,
            },
        ]
        inventory_entries = [
            {
                "item": "Laptop Model X1",
                "qty": 1.0,
                "rate": 60000.0,
                "amount": 60000.0,
                "uom": "Nos",
                "godown": "Main Location",
                "discount": 0.0,
            }
        ]

        xml_str = tally_xml_builder.build_voucher_xml(
            voucher_type="Sales",
            voucher_number="INV-2026-001",
            date="2026-04-05",
            party_ledger="Alpha Technologies Pvt Ltd",
            ledger_entries=ledger_entries,
            inventory_entries=inventory_entries,
            narration="Sales Invoice for Q1 Hardware Supplies",
            reference="PO-ALPHA-99",
            guid="test-guid-vch-001"
        )
        self.assertIn('<VOUCHER VCHTYPE="Sales"', xml_str)
        self.assertIn("<VOUCHERNUMBER>INV-2026-001</VOUCHERNUMBER>", xml_str)

        root = tally_xml_parser.parse_tally_xml_root(xml_str)
        vouchers = tally_xml_parser.parse_vouchers_from_xml(root)
        self.assertEqual(len(vouchers), 1)
        v = vouchers[0]
        self.assertEqual(v["voucher_type"], "Sales")
        self.assertEqual(v["voucher_number"], "INV-2026-001")
        self.assertEqual(len(v["ledger_entries"]), 4)
        self.assertEqual(len(v["inventory_entries"]), 1)
        self.assertEqual(v["inventory_entries"][0]["item"], "Laptop Model X1")
        self.assertEqual(v["inventory_entries"][0]["amount"], 60000.0)

    def test_import_envelope_wrapping(self):
        msg = tally_xml_builder.build_unit_xml(name="Kgs", formal_name="Kilograms", decimal_places=2, uqc="KGS")
        envelope = tally_xml_builder.wrap_import_envelope([msg], company_name="Scidecs Demo Ltd")
        self.assertIn("<TALLYREQUEST>Import</TALLYREQUEST>", envelope)
        self.assertIn("<TYPE>Data</TYPE>", envelope)
        self.assertIn("<SVCURRENTCOMPANY>Scidecs Demo Ltd</SVCURRENTCOMPANY>", envelope)
        self.assertIn("<UNIT NAME=\"Kgs\"", envelope)

    def test_opening_balance_has_native_ledger_collection(self):
        self.assertEqual(tally_xml_builder.COLLECTION_MAP["opening_balance"], "Ledger")

    def test_xml_attributes_escape_quotes(self):
        xml_str = tally_xml_builder.build_party_ledger_xml(
            name='M/s "Sharma" & Sons', parent="Sundry Debtors")
        self.assertIn('NAME="M/s &quot;Sharma&quot; &amp; Sons"', xml_str)
        self.assertIsNotNone(tally_xml_parser.parse_tally_xml_root(xml_str))

    def test_ledger_collection_is_classified_once(self):
        xml_str = """<ENVELOPE><LEDGER NAME="Customer">
          <PARENT>Sundry Debtors</PARENT></LEDGER>
          <LEDGER NAME="Sales"><PARENT>Sales Accounts</PARENT></LEDGER>
          <LEDGER NAME="CGST 9%"><PARENT>Duties &amp; Taxes</PARENT>
          <TAXTYPE>GST</TAXTYPE><GSTDUTYHEAD>CGST</GSTDUTYHEAD></LEDGER></ENVELOPE>"""
        records = tally_xml_parser.parse_ledgers_from_xml(
            tally_xml_parser.parse_tally_xml_root(xml_str))
        self.assertEqual([r["name"] for r in tally_xml_parser.filter_ledgers_for_entity(records, "ledger")], ["Customer"])
        self.assertEqual([r["name"] for r in tally_xml_parser.filter_ledgers_for_entity(records, "account_ledger")], ["Sales"])
        self.assertEqual([r["name"] for r in tally_xml_parser.filter_ledgers_for_entity(records, "tax")], ["CGST 9%"])
        self.assertEqual(
            [r["name"] for r in tally_xml_parser.filter_ledgers_for_entity(records, "opening_balance")],
            ["Customer", "Sales"],
        )

    def test_inventory_gst_rate_is_parsed(self):
        xml_str = """<ENVELOPE><VOUCHER VCHTYPE="Sales"><VOUCHERNUMBER>S-1</VOUCHERNUMBER>
          <ALLINVENTORYENTRIES.LIST><STOCKITEMNAME>Item</STOCKITEMNAME>
          <ACTUALQTY>1 Nos</ACTUALQTY><RATE>100/Nos</RATE><AMOUNT>-100</AMOUNT>
          <GSTRATEDETAILS.LIST><GSTRATE>18</GSTRATE></GSTRATEDETAILS.LIST>
          </ALLINVENTORYENTRIES.LIST></VOUCHER></ENVELOPE>"""
        voucher = tally_xml_parser.parse_vouchers_from_xml(
            tally_xml_parser.parse_tally_xml_root(xml_str))[0]
        self.assertEqual(voucher["inventory_entries"][0]["gst_rate"], 18.0)


if __name__ == "__main__":
    unittest.main()
