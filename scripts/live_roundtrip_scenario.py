#!/usr/bin/env python3
"""Seed, dispatch, snapshot, and verify the destructive live Tally round trip."""
import argparse
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

PREFIX = "RT260904"
PRODUCTS = [
    ("Hydraulic Pump 5HP", "84136090", 7200.0, 9500.0),
    ("Industrial Valve 50mm", "84818030", 1200.0, 1750.0),
    ("Steel Pipe 2 Inch", "73063000", 450.0, 650.0),
    ("Ball Bearing 6205", "84821090", 280.0, 420.0),
    ("Electric Motor 3HP", "85015220", 8400.0, 11200.0),
    ("Pressure Gauge 10Bar", "90262000", 650.0, 900.0),
    ("Copper Cable 4Sqmm", "85444999", 95.0, 140.0),
    ("Safety Helmet ISI", "65061010", 320.0, 480.0),
    ("Welding Electrode E6013", "83111000", 180.0, 260.0),
    ("Gear Oil 20L", "27101980", 2400.0, 3200.0),
    ("Pneumatic Cylinder 32mm", "84123100", 1650.0, 2300.0),
    ("Flange Class 150", "73079190", 520.0, 760.0),
    ("Control Relay 24V", "85364900", 410.0, 620.0),
    ("Stainless Fastener Kit", "73181500", 750.0, 1050.0),
    ("Industrial Grease 5Kg", "27101990", 980.0, 1380.0),
]


def configure_odoo(config, database):
    odoo.tools.config.parse_config(["-c", str(config), "-d", database, "--no-http"])


def one(model, domain, values):
    record = model.search(domain, limit=1)
    return record or model.create(values)


def seed(env, instance):
    from odoo.addons.tally_integration.services.sync_engine import SyncEngine

    entities = {
        "account_ledger", "ledger", "uom", "stock_group", "stock_item", "godown",
        "cost_centre", "tax", "sales", "credit_note", "purchase", "debit_note",
        "receipt", "payment", "journal", "contra", "stock_journal",
    }
    for entity in entities:
        cfg = instance.entity_config_ids.filtered(lambda c: c.entity == entity)[:1]
        vals = {"enabled": True, "direction": "both", "source_of_truth": "bidirectional"}
        if cfg:
            cfg.write(vals)
        else:
            env["tally.entity.config"].create(dict(vals, instance_id=instance.id, entity=entity))

    engine = SyncEngine(env, instance)
    company = instance.company_id
    income = engine._get_or_create_account(f"{PREFIX} Sales Account", "income")
    expense = engine._get_or_create_account(f"{PREFIX} Purchase Account", "expense")
    bank = engine._get_or_create_account(f"{PREFIX} Test Bank", "asset_cash")
    office = engine._get_or_create_account(f"{PREFIX} Office Expense", "expense")

    customer = one(env["res.partner"], [("name", "=", f"{PREFIX} Customer Maharashtra")], {
        "name": f"{PREFIX} Customer Maharashtra", "company_id": company.id,
        "customer_rank": 1, "email": "roundtrip.customer@example.com",
    })
    vendor = one(env["res.partner"], [("name", "=", f"{PREFIX} Vendor Maharashtra")], {
        "name": f"{PREFIX} Vendor Maharashtra", "company_id": company.id,
        "supplier_rank": 1, "email": "roundtrip.vendor@example.com",
    })
    engine._ensure_partner_accounts(customer)
    engine._ensure_partner_accounts(vendor)

    tax_specs = (
        ("Output CGST 9%", "sale"), ("Output SGST 9%", "sale"),
        ("Input CGST 9%", "purchase"), ("Input SGST 9%", "purchase"),
    )
    taxes = {}
    for label, usage in tax_specs:
        name = f"{PREFIX} {label}"
        taxes[label] = one(env["account.tax"], [
            ("name", "=", name), ("company_id", "=", company.id),
            ("type_tax_use", "=", usage),
        ], {"name": name, "amount": 9.0, "amount_type": "percent",
            "type_tax_use": usage, "company_id": company.id})

    categories = []
    for label in ("Hydraulics", "Electrical", "Industrial Consumables"):
        categories.append(one(env["product.category"], [("name", "=", f"{PREFIX} {label}")], {
            "name": f"{PREFIX} {label}",
        }))

    # Ensure standard UoM is enqueued
    uom = env["uom.uom"].search([("name", "=", "Units")], limit=1)
    if uom:
        uom._enqueue_tally_uom()
    income._enqueue_tally_account()
    expense._enqueue_tally_account()
    bank._enqueue_tally_account()
    office._enqueue_tally_account()
    customer._enqueue_tally_party()
    vendor._enqueue_tally_party()
    for t in taxes.values():
        t._enqueue_tally_tax()
    for cat in categories:
        cat._enqueue_tally_stock_group()

    products = []
    Product = env["product.product"]
    for index, (label, hsn, cost, price) in enumerate(PRODUCTS, 1):
        name = f"{PREFIX} {index:02d} {label}"
        vals = {
            "name": name, "default_code": f"{PREFIX}-P{index:02d}",
            "barcode": f"260904{index:06d}", "is_storable": True,
            "standard_price": cost, "list_price": price,
            "categ_id": categories[(index - 1) % len(categories)].id,
            "property_account_income_id": income.id,
            "property_account_expense_id": expense.id,
            "company_id": company.id,
        }
        if "l10n_in_hsn_code" in Product._fields:
            vals["l10n_in_hsn_code"] = hsn
        prod = one(Product, [("default_code", "=", vals["default_code"])], vals)
        prod.product_tmpl_id._enqueue_tally_product()
        products.append(prod)

    sale_journal = engine._get_or_create_journal("sale")
    purchase_journal = engine._get_or_create_journal("purchase")
    general_journal = engine._get_or_create_journal("general")
    bank_journal = env["account.journal"].search([
        ("type", "=", "bank"), ("company_id", "=", company.id),
    ], limit=1)
    if not bank_journal:
        bank_journal = env["account.journal"].create({
            "name": f"{PREFIX} Bank", "code": "RTBNK", "type": "bank",
            "company_id": company.id, "default_account_id": bank.id,
        })
    elif not bank_journal.default_account_id:
        bank_journal.default_account_id = bank.id

    def invoice(ref, move_type, partner, selected, qty, taxes_for_lines, journal, account):
        Move = env["account.move"]
        move = Move.search([("ref", "=", ref), ("company_id", "=", company.id)], limit=1)
        if move:
            return move
        move = Move.create({
            "move_type": move_type, "partner_id": partner.id, "invoice_date": "2026-09-01",
            "ref": ref, "journal_id": journal.id,
            "invoice_line_ids": [(0, 0, {
                "name": product.name, "product_id": product.id, "quantity": qty,
                "price_unit": product.list_price if move_type.startswith("out_") else product.standard_price,
                "account_id": account.id, "tax_ids": [(6, 0, taxes_for_lines.ids)],
            }) for product in selected],
        })
        move.action_post()
        return move

    purchase_taxes = taxes["Input CGST 9%"] | taxes["Input SGST 9%"]
    sale_taxes = taxes["Output CGST 9%"] | taxes["Output SGST 9%"]
    moves = [
        invoice(f"{PREFIX}-PUR-01", "in_invoice", vendor, products[:8], 10, purchase_taxes, purchase_journal, expense),
        invoice(f"{PREFIX}-PUR-02", "in_invoice", vendor, products[8:], 12, purchase_taxes, purchase_journal, expense),
        invoice(f"{PREFIX}-SAL-01", "out_invoice", customer, products[:7], 3, sale_taxes, sale_journal, income),
        invoice(f"{PREFIX}-SAL-02", "out_invoice", customer, products[7:], 4, sale_taxes, sale_journal, income),
        invoice(f"{PREFIX}-PRET-01", "in_refund", vendor, products[1:3], 2, purchase_taxes, purchase_journal, expense),
        invoice(f"{PREFIX}-SRET-01", "out_refund", customer, products[:2], 1, sale_taxes, sale_journal, income),
    ]

    def payment(memo, payment_type, partner, amount):
        Payment = env["account.payment"]
        record = Payment.search([("memo", "=", memo), ("company_id", "=", company.id)], limit=1)
        if record:
            return record
        record = Payment.create({
            "payment_type": payment_type,
            "partner_type": "customer" if payment_type == "inbound" else "supplier",
            "partner_id": partner.id, "amount": amount, "date": "2026-09-01",
            "journal_id": bank_journal.id, "memo": memo,
        })
        record.action_post()
        return record

    payments = [
        payment(f"{PREFIX}-RECEIPT-01", "inbound", customer, 25000.0),
        payment(f"{PREFIX}-PAYMENT-01", "outbound", vendor, 30000.0),
    ]

    journal_ref = f"{PREFIX}-JRN-01"
    journal_move = env["account.move"].search([("ref", "=", journal_ref)], limit=1)
    if not journal_move:
        journal_move = env["account.move"].create({
            "move_type": "entry", "date": "2026-09-01", "ref": journal_ref,
            "journal_id": general_journal.id,
            "line_ids": [(0, 0, {"name": journal_ref, "account_id": office.id, "debit": 1500.0}),
                         (0, 0, {"name": journal_ref, "account_id": bank.id, "credit": 1500.0})],
        })
        journal_move.action_post()
    moves.append(journal_move)

    warehouse = env["stock.warehouse"].search([("company_id", "=", company.id)], limit=1)
    secondary = one(env["stock.location"], [
        ("name", "=", f"{PREFIX} Secondary Godown"), ("company_id", "=", company.id),
    ], {"name": f"{PREFIX} Secondary Godown", "location_id": warehouse.lot_stock_id.id,
        "usage": "internal", "company_id": company.id})
    secondary._enqueue_tally_godown()
    for index, product in enumerate(products):
        purchased = 10 if index < 8 else 12
        sold = 3 if index < 7 else 4
        purchase_return = 2 if index in (1, 2) else 0
        sale_return = 1 if index in (0, 1) else 0
        engine._set_location_quant(product, warehouse.lot_stock_id,
                                   purchased - sold - purchase_return + sale_return)

    transfer_origin = f"{PREFIX}-STJ-01"
    transfer = env["stock.picking"].search([("origin", "=", transfer_origin)], limit=1)
    if not transfer:
        transfer = env["stock.picking"].create({
            "picking_type_id": warehouse.int_type_id.id,
            "location_id": warehouse.lot_stock_id.id, "location_dest_id": secondary.id,
            "origin": transfer_origin,
            "move_ids": [(0, 0, {
                "description_picking": p.name, "product_id": p.id,
                "product_uom_qty": 1.0, "product_uom": p.uom_id.id,
                "location_id": warehouse.lot_stock_id.id, "location_dest_id": secondary.id,
            }) for p in products[:5]],
        })
        transfer.action_confirm()
        transfer.move_ids.quantity = 1.0
        transfer.button_validate()

    return {"products": products, "moves": moves, "payments": payments, "transfer": transfer,
            "customer": customer, "vendor": vendor}


def snapshot(env, instance, path):
    products = env["product.product"].search([("default_code", "=like", f"{PREFIX}-P%")], order="default_code")
    moves = env["account.move"].search([("ref", "=like", f"{PREFIX}-%")], order="ref")
    data = {
        "prefix": PREFIX, "tally_company": instance.tally_company,
        "products": [{"name": p.name, "code": p.default_code, "qty": p.qty_available,
                      "cost": p.standard_price, "price": p.list_price} for p in products],
        "moves": [{"ref": m.ref, "type": m.move_type, "state": m.state,
                   "untaxed": m.amount_untaxed, "tax": m.amount_tax,
                   "total": m.amount_total} for m in moves],
        "payments": [{"memo": p.memo, "type": p.payment_type, "amount": p.amount,
                      "state": p.state} for p in env["account.payment"].search([
                          ("memo", "=like", f"{PREFIX}-%")])],
        "queue": {state: env["tally.sync.queue"].search_count([
            ("instance_id", "=", instance.id), ("payload", "ilike", PREFIX), ("state", "=", state)])
                  for state in ("pending", "sent", "acked", "failed")},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str))
    return data


def verify(env, instance, expected_path):
    expected = json.loads(expected_path.read_text())
    actual_products = env["product.product"].search([("name", "=like", f"{PREFIX} %")])
    invoice_moves = env["account.move"].search([("ref", "=like", f"{PREFIX}-%")])
    payments = env["account.payment"].search([])
    journal_moves = env["account.move"].search([("move_type", "=", "entry")])
    transfers = env["stock.picking"].search([])
    mappings = env["tally.mapping"].search([("instance_id", "=", instance.id)])

    expected_invoice_refs = {
        m["ref"] for m in expected["moves"]
        if m["ref"].startswith(f"{PREFIX}-")
        and not any(tag in m["ref"] for tag in ("-JRN-", "-PAYMENT-", "-RECEIPT-"))
    }
    actual_invoice_refs = set(invoice_moves.mapped("ref"))

    result = {
        "expected_product_count": len(expected["products"]),
        "actual_product_count": len(actual_products),
        "missing_invoice_refs": sorted(expected_invoice_refs - actual_invoice_refs),
        "actual_invoice_count": len(invoice_moves),
        "recovered_payments_count": len(payments),
        "recovered_journal_entries_count": len(journal_moves),
        "recovered_transfers_count": len(transfers),
        "mapping_count": len(mappings),
    }
    result["ok"] = (
        result["actual_product_count"] >= result["expected_product_count"]
        and not result["missing_invoice_refs"]
        and result["recovered_payments_count"] >= 2
        and result["recovered_journal_entries_count"] >= 1
        and result["recovered_transfers_count"] >= 1
        and result["mapping_count"] >= 45
    )
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("seed", "push", "snapshot", "verify"))
    parser.add_argument("--database", default="odootally_local")
    parser.add_argument("--instance-id", type=int, default=1)
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "odoo-local.conf")
    parser.add_argument("--expected", type=Path,
                        default=ROOT / "artifacts" / "roundtrip_expected.json")
    args = parser.parse_args()
    configure_odoo(args.config, args.database)
    registry = Registry(args.database)
    with registry.cursor() as cr:
        env = api.Environment(cr, SUPERUSER_ID, {})
        instance = env["tally.instance"].browse(args.instance_id).exists()
        if not instance:
            raise SystemExit(f"Tally instance {args.instance_id} does not exist")
        # Ensure live Tally is online
        import urllib.request
        live_url = f"http://{instance.tally_host}:{instance.tally_port}"
        try:
            test_req = urllib.request.Request(
                live_url,
                data=b"<ENVELOPE><HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Collection</TYPE><ID>Company</ID></HEADER><BODY><DESC><STATICVARIABLES><SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT></STATICVARIABLES></DESC></BODY></ENVELOPE>",
                headers={"Content-Type": "text/xml"}
            )
            with urllib.request.urlopen(test_req, timeout=5) as r:
                pass
        except Exception as e:
            raise SystemExit(f"[PAUSED] Real Live Tally server at {live_url} is offline: {e}")

        if args.mode == "seed":
            seeded = seed(env, instance)
            cr.commit()
            result = snapshot(env, instance, args.expected)
            result["seeded"] = {key: len(value) if hasattr(value, "__len__") else value.id
                                for key, value in seeded.items()}
        elif args.mode == "push":
            instance._direct_dispatch_queue(limit=500, batch_size=20)
            cr.commit()
            result = snapshot(env, instance, args.expected)
        elif args.mode == "snapshot":
            result = snapshot(env, instance, args.expected)
        else:
            result = verify(env, instance, args.expected)
        print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
