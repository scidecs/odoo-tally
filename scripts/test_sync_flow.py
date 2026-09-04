#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Simulated end-to-end sync test for Tally Integration."""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "tally_integration")))

from services import tally_xml_builder, tally_xml_parser
from services.sync_engine import compute_payload_hash


class TestEndToEndSyncFlow(unittest.TestCase):

    def test_echo_suppression_hashing(self):
        """Verify that equivalent payloads yield identical hashes."""
        payload_1 = {
            "name": "Acme Corp",
            "parent": "Sundry Debtors",
            "gstin": "27AAACA1234A1Z5",
            "state": "Maharashtra",
        }
        payload_2 = {
            "state": "Maharashtra",
            "name": "Acme Corp",
            "gstin": "27AAACA1234A1Z5",
            "parent": "Sundry Debtors",
        }
        hash_1 = compute_payload_hash(payload_1)
        hash_2 = compute_payload_hash(payload_2)
        self.assertEqual(hash_1, hash_2, "Hashes must be identical regardless of key order")

    def test_full_roundtrip_voucher(self):
        """Simulate creating an invoice in Odoo, building XML, and parsing it on Tally side."""
        # 1. Build Outbound Voucher XML
        xml_out = tally_xml_builder.build_voucher_xml(
            voucher_type="Sales",
            voucher_number="INV/2026/00042",
            date="2026-05-10",
            party_ledger="Globex Corporation",
            ledger_entries=[
                {"ledger": "Globex Corporation", "amount": 118000.0, "bill_allocations": [{"type": "New Ref", "name": "INV/2026/00042", "amount": 118000.0}]},
                {"ledger": "Sales Account", "amount": -100000.0},
                {"ledger": "Output IGST @ 18%", "amount": -18000.0},
            ],
            inventory_entries=[
                {"item": "Industrial Pump A1", "qty": 2.0, "rate": 50000.0, "amount": 100000.0, "uom": "Nos", "godown": "Factory Godown", "discount": 0.0}
            ],
            narration="Annual machinery supply",
            reference="PO-GLOBEX-42"
        )
        envelope = tally_xml_builder.wrap_import_envelope([xml_out], company_name="Scidecs Demo Ltd")

        # 2. Simulate Tally Parsing the XML
        root = tally_xml_parser.parse_tally_xml_root(envelope)
        self.assertIsNotNone(root)
        vouchers = tally_xml_parser.parse_vouchers_from_xml(root)
        self.assertEqual(len(vouchers), 1)

        v = vouchers[0]
        self.assertEqual(v["voucher_number"], "INV/2026/00042")
        self.assertEqual(v["party_ledger"], "Globex Corporation")
        self.assertEqual(len(v["inventory_entries"]), 1)
        self.assertEqual(v["inventory_entries"][0]["godown"], "Factory Godown")
        self.assertEqual(len(v["ledger_entries"]), 3)


if __name__ == "__main__":
    unittest.main()
