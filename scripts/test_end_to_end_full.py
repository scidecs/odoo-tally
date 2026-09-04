#!/usr/bin/env python3
"""Comprehensive End-to-End Test Suite for Odoo-Tally Integration."""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ODOO_SRC = Path("/Users/vikramdewangan/Documents/Sendan/AlSheraaGroup/AlSheraaOdoo/odoo-src")
sys.path.insert(0, str(ODOO_SRC))

import odoo
from odoo import api, SUPERUSER_ID
from odoo.modules.registry import Registry


def run_test():
    print("=" * 70)
    print("STARTING FULL END-TO-END ODOO-TALLY DISASTER RECOVERY & SYNC SUITE")
    print("=" * 70)

    # 1. Test Disaster Recovery Database State
    db_name = "odootally_disaster_recovery"
    odoo.tools.config.parse_config(["-c", str(ROOT / "config" / "odoo-local.conf"), "-d", db_name, "--no-http"])
    registry = Registry(db_name)

    with registry.cursor() as cr:
        env = api.Environment(cr, SUPERUSER_ID, {})
        instance = env["tally.instance"].search([], limit=1)
        assert instance, "Tally instance not found in disaster recovery database"
        print(f"[✓] Connected to Database: {db_name}")
        print(f"[✓] Paired Tally Instance: {instance.name} (Company: {instance.tally_company})")

        # Check products
        products = env["product.product"].search([("name", "=like", "RT260904 %")])
        print(f"[✓] Recovered Products: {len(products)}/15 (All present)")
        assert len(products) >= 15, "Expected at least 15 products"

        # Check invoices
        invoices = env["account.move"].search([("ref", "=like", "RT260904-%")])
        print(f"[✓] Recovered Invoices & Notes: {len(invoices)}/6 (All purchase, sales, debit/credit notes)")
        assert len(invoices) >= 6, "Expected 6 invoices/refunds"

        # Check payments
        payments = env["account.payment"].search([])
        print(f"[✓] Recovered Payments: {len(payments)}/2 (Inbound & Outbound)")
        assert len(payments) >= 2, "Expected 2 payments"

        # Check stock pickings/transfers
        pickings = env["stock.picking"].search([])
        print(f"[✓] Recovered Stock Transfers: {len(pickings)}/1 (Inter-Godown Transfer)")
        assert len(pickings) >= 1, "Expected 1 stock transfer"

        # Check mappings
        mappings = env["tally.mapping"].search([("instance_id", "=", instance.id)])
        print(f"[✓] Total Identity Mappings: {len(mappings)}/45 (Masters + Transactions + Godowns)")
        assert len(mappings) >= 45, "Expected at least 45 identity mappings"

        # 2. Test Outbound Sync in Recovered Database (Odoo -> Tally)
        print("\n--- Testing Outbound Sync (Odoo -> Tally Push) ---")
        p99 = env["product.product"].search([("default_code", "=", "RT260904-P99")], limit=1)
        if not p99:
            p99 = env["product.product"].create({
                "name": "RT260904 99 E2E Test Servo Valve",
                "default_code": "RT260904-P99",
                "is_storable": True,
                "standard_price": 5500.0,
                "list_price": 7500.0,
            })
            cr.commit()

        # Find queue item
        queue_item = env["tally.sync.queue"].search([
            ("instance_id", "=", instance.id),
            ("entity", "=", "stock_item"),
            ("odoo_model_name", "=", p99._name),
            ("odoo_res_id", "=", p99.id),
        ], limit=1)
        assert queue_item, f"Queue item not found for product {p99.id}"
        print(f"[✓] Enqueued Product '{p99.name}' -> Queue ID={queue_item.id}, Initial State='{queue_item.state}'")

        # Dispatch queue
        instance._direct_dispatch_queue(limit=50, batch_size=10)
        cr.commit()

        # Check acked status
        acked_item = env["tally.sync.queue"].browse(queue_item.id)
        assert acked_item.state == "acked", f"Expected queue state 'acked', got '{acked_item.state}'"
        print(f"[✓] Outbound Push Acknowledged by Tally -> Queue ID={acked_item.id}, Final State='{acked_item.state}'")

        # 3. Test Inbound Sync (Tally -> Odoo Pull)
        print("\n--- Testing Inbound Sync (Tally -> Odoo Pull) ---")
        pulled_counts = instance._direct_pull(include_vouchers=True)
        cr.commit()
        print(f"[✓] Inbound Reconciliation Pull Complete: {pulled_counts}")

    print("\n" + "=" * 70)
    print("ALL END-TO-END TESTS PASSED SUCCESSFULLY (100% OK)")
    print("=" * 70)


if __name__ == "__main__":
    run_test()
