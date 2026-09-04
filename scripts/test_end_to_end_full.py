#!/usr/bin/env python3
"""Comprehensive End-to-End Test Suite against REAL LIVE Tally Server."""
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ODOO_SRC = Path("/Users/vikramdewangan/Documents/Sendan/AlSheraaGroup/AlSheraaOdoo/odoo-src")
sys.path.insert(0, str(ODOO_SRC))

import odoo
from odoo import api, SUPERUSER_ID
from odoo.modules.registry import Registry


def check_live_server_online(host, port):
    """Verify the real Tally server is online before running tests."""
    url = f"http://{host}:{port}"
    payload = "<ENVELOPE><HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Collection</TYPE><ID>Company</ID></HEADER><BODY><DESC><STATICVARIABLES><SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT></STATICVARIABLES></DESC></BODY></ENVELOPE>"
    req = urllib.request.Request(url, data=payload.encode("utf-8"), headers={"Content-Type": "text/xml"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            content = resp.read().decode("utf-8")
            if "<COMPANY" in content or "<ENVELOPE" in content:
                return True
    except Exception as e:
        print(f"[ERROR] Live Tally server at {url} is unreachable: {e}")
        return False
    return False


def run_test():
    print("=" * 70)
    print("STARTING LIVE END-TO-END TEST ON REAL TALLY SERVER (NO MOCKS)")
    print("=" * 70)

    db_name = "odootally_local"
    odoo.tools.config.parse_config(["-c", str(ROOT / "config" / "odoo-local.conf"), "-d", db_name, "--no-http"])
    registry = Registry(db_name)

    with registry.cursor() as cr:
        env = api.Environment(cr, SUPERUSER_ID, {})
        instance = env["tally.instance"].search([("active", "=", True)], limit=1)
        assert instance, f"Active Tally instance not found in {db_name}"

        # 1. Check live instance connectivity
        host = instance.tally_host
        port = instance.tally_port
        print(f"[*] Checking Live Tally Server connectivity at http://{host}:{port}...")
        if not check_live_server_online(host, port):
            print(f"[!] REAL TALLY INSTANCE AT http://{host}:{port} IS OFFLINE. PAUSING TEST EXECUTION.")
            sys.exit(1)
        print(f"[✓] Real Tally instance online at http://{host}:{port} (Company: {instance.tally_company})")

        # 2. Test Outbound Push to Real Live Tally
        print("\n--- Phase 1: Real Live Outbound Push (Odoo -> Tally) ---")
        p_code = "LIVE-TEST-001"
        prod = env["product.product"].search([("default_code", "=", p_code)], limit=1)
        if not prod:
            prod = env["product.product"].create({
                "name": "Live Real Hydraulic Cylinder 40mm",
                "default_code": p_code,
                "is_storable": True,
                "standard_price": 3200.0,
                "list_price": 4800.0,
            })
            prod.product_tmpl_id._enqueue_tally_product()
            cr.commit()

        # Find queue item
        queue_item = env["tally.sync.queue"].search([
            ("instance_id", "=", instance.id),
            ("entity", "=", "stock_item"),
            ("odoo_model_name", "=", prod._name),
            ("odoo_res_id", "=", prod.id),
        ], order="id desc", limit=1)

        if not queue_item or queue_item.state != "acked":
            print(f"[*] Dispatching queue item to live Tally...")
            instance._direct_dispatch_queue(limit=50, batch_size=10)
            cr.commit()
            if queue_item:
                queue_item.invalidate_recordset()

        queue_item = env["tally.sync.queue"].search([
            ("instance_id", "=", instance.id),
            ("entity", "=", "stock_item"),
            ("odoo_model_name", "=", prod._name),
            ("odoo_res_id", "=", prod.id),
        ], order="id desc", limit=1)
        assert queue_item, f"Queue item for {prod.name} not found"
        print(f"[✓] Real Tally Outbound Response -> Queue ID={queue_item.id}, State='{queue_item.state}'")
        assert queue_item.state == "acked", f"Expected queue state 'acked', got {queue_item.state}"

        # 3. Test Real Live Inbound Pull (Tally -> Odoo)
        print("\n--- Phase 2: Real Live Inbound Pull (Tally -> Odoo) ---")
        pulled = instance._direct_pull(include_vouchers=True)
        cr.commit()
        print(f"[✓] Real Tally Inbound Pull Successful: {pulled} entities processed")

        # 4. Verify Identity Mapping on Real Instance
        mappings = env["tally.mapping"].search([("instance_id", "=", instance.id)])
        print(f"[✓] Real Tally Identity Mappings in Odoo: {len(mappings)} records active")
        assert len(mappings) > 0, "No mappings found after sync"

    print("\n" + "=" * 70)
    print("REAL LIVE TALLY SERVER END-TO-END VERIFICATION COMPLETED (100% OK)")
    print("=" * 70)


if __name__ == "__main__":
    run_test()
