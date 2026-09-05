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

PREFIX = "RT260904F"
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

    instance.tally_educational_mode = True
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
            "barcode": f"260906{index:06d}", "is_storable": True,
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
    bank_journal.default_account_id._enqueue_tally_account()

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
        target_total = purchased - sold - purchase_return + sale_return
        secondary_qty = sum(env["stock.quant"].search([
            ("product_id", "=", product.id), ("location_id", "=", secondary.id),
        ]).mapped("quantity"))
        engine._set_location_quant(product, warehouse.lot_stock_id,
                                   target_total - secondary_qty)

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

    # Rebuild transactional payloads after educational-mode date normalization.
    unit = env.ref("uom.product_uom_unit", raise_if_not_found=False)
    if unit:
        unit._enqueue_tally_uom()
    for move in moves:
        move._enqueue_tally_voucher()
    for record in payments:
        record._enqueue_tally_payment()
    transfer._enqueue_tally_stock_journal()

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
    invoice_moves = env["account.move"].search([
        ("ref", "=like", f"{PREFIX}-%"),
        ("move_type", "in", ("out_invoice", "out_refund", "in_invoice", "in_refund")),
    ])
    payments = env["account.payment"].search([("memo", "=like", f"{PREFIX}-%")])
    journal_moves = env["account.move"].search([
        ("move_type", "=", "entry"), ("ref", "=like", f"{PREFIX}-JRN-%")])
    transfers = env["stock.picking"].search([("origin", "=like", f"{PREFIX}-%")])
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
        "unexpected_invoice_refs": sorted(actual_invoice_refs - expected_invoice_refs),
        "actual_invoice_count": len(invoice_moves),
        "recovered_payments_count": len(payments),
        "recovered_journal_entries_count": len(journal_moves),
        "recovered_transfers_count": len(transfers),
        "invoice_mismatches": {},
        "product_quantity_mismatches": {},
        "payments": sorted((p.memo, p.payment_type, float(p.amount)) for p in payments),
        "transfers": sorted((p.origin, p.state) for p in transfers),
        "mapping_count": len(mappings),
        "sync_log_error_count": env["tally.sync.log"].search_count([
            ("instance_id", "=", instance.id), ("status", "=", "error"),
        ]),
    }
    expected_moves = {m["ref"]: m for m in expected["moves"]
                      if m["ref"] in expected_invoice_refs}
    actual_moves = {m.ref: m for m in invoice_moves if m.ref in expected_invoice_refs}
    for ref, exp in expected_moves.items():
        move = actual_moves.get(ref)
        if not move or any(abs(float(got) - float(exp[key])) > 0.01 for key, got in (
                ("untaxed", move.amount_untaxed), ("tax", move.amount_tax),
                ("total", move.amount_total))):
            result["invoice_mismatches"][ref] = {
                "expected": [exp["untaxed"], exp["tax"], exp["total"]],
                "actual": ([float(move.amount_untaxed), float(move.amount_tax),
                            float(move.amount_total)] if move else None),
            }
    expected_products = {p["name"]: p for p in expected["products"]}
    actual_product_map = {p.name: p for p in actual_products}
    expected_categories = ("Hydraulics", "Electrical", "Industrial Consumables")
    for product_index, (name, exp) in enumerate(expected_products.items()):
        product = actual_product_map.get(name)
        expected_category = f"{PREFIX} {expected_categories[product_index % 3]}"
        actual_values = (None if not product else {
            "qty": float(product.qty_available), "cost": float(product.standard_price),
            "price": float(product.list_price), "code": product.default_code,
            "category": product.categ_id.name,
        })
        if (not product or actual_values["code"] != exp["code"]
                or actual_values["category"] != expected_category
                or any(abs(actual_values[key] - float(exp[key])) > 0.0001
                       for key in ("qty", "cost", "price"))):
            result["product_quantity_mismatches"][name] = {
                "expected": dict({k: exp[k] for k in ("qty", "cost", "price", "code")},
                                 category=expected_category),
                "actual": actual_values,
            }
    expected_payment_rows = sorted(
        (p["memo"], p["type"], float(p["amount"])) for p in expected["payments"])
    actual_payment_rows = sorted(
        (p.memo, p.payment_type, float(p.amount)) for p in payments)
    result["ok"] = (
        result["actual_product_count"] == result["expected_product_count"]
        and not result["missing_invoice_refs"]
        and not result["unexpected_invoice_refs"]
        and result["actual_invoice_count"] == len(expected_invoice_refs)
        and not result["invoice_mismatches"]
        and not result["product_quantity_mismatches"]
        and actual_payment_rows == expected_payment_rows
        and result["recovered_journal_entries_count"] == 1
        and sorted((p.origin, p.state) for p in transfers) == [(f"{PREFIX}-STJ-01", "done")]
        and result["mapping_count"] >= 45
        and result["sync_log_error_count"] == 0
    )
    return result


def bootstrap(env):
    """Configure a newly-created Odoo database for the recovery pull."""
    company = env.company
    india = env["res.country"].search([("code", "=", "IN")], limit=1)
    inr = env["res.currency"].with_context(active_test=False).search(
        [("name", "=", "INR")], limit=1)
    vals = {"name": "Scidecs Tally Recovery Test"}
    if india:
        vals["country_id"] = india.id
    if inr:
        inr.active = True
        vals["currency_id"] = inr.id
    company.write(vals)
    instance = env["tally.instance"].create({
        "name": "Scidecs Demo Tally Recovery",
        "company_id": company.id,
        "connection_mode": "direct",
        "tally_host": "192.168.68.103",
        "tally_port": 9000,
        "tally_protocol": "http",
        "tally_company": "Scidecs Demo Pvt Ltd",
        "odoo_role": "full",
        "tally_inventory": "with_inventory",
        "tally_educational_mode": True,
        "history_from": "2026-09-01",
        "pull_lookback_days": 30,
        "auto_post": True,
        "direct_auto_pull": False,
        "verbose_logging": True,
        "default_source": "tally",
    })
    instance.action_load_default_entities()
    instance.entity_config_ids.write({
        "enabled": True, "direction": "both", "source_of_truth": "bidirectional",
    })
    return instance


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("bootstrap", "seed", "push", "pull", "snapshot",
                                         "verify", "alter-product", "inspect-product",
                                         "set-odoo-price", "inspect-tally-product",
                                         "restore-products", "verify-tally-products"))
    parser.add_argument("--database", default="odootally_local")
    parser.add_argument("--instance-id", type=int, default=1)
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "odoo-local.conf")
    parser.add_argument("--expected", type=Path,
                        default=ROOT / "artifacts" / "roundtrip_expected.json")
    parser.add_argument("--output", type=Path,
                        help="Optional path for the JSON result/evidence file")
    parser.add_argument("--product-name",
                        default=f"{PREFIX} 15 Industrial Grease 5Kg")
    parser.add_argument("--price", type=float,
                        help="Selling price used by alter-product")
    parser.add_argument("--effective-date", default="2026-09-01",
                        help="Applicable-from date for alter-product (YYYY-MM-DD)")
    args = parser.parse_args()
    configure_odoo(args.config, args.database)
    registry = Registry(args.database)
    with registry.cursor() as cr:
        env = api.Environment(cr, SUPERUSER_ID, {})
        if args.mode == "bootstrap":
            instance = bootstrap(env)
            cr.commit()
            print(json.dumps({"instance_id": instance.id, "company": instance.company_id.name,
                              "entity_count": len(instance.entity_config_ids)}, indent=2))
            return
        instance = env["tally.instance"].browse(args.instance_id).exists()
        if not instance:
            raise SystemExit(f"Tally instance {args.instance_id} does not exist")
        # Only network modes require Tally. Snapshot and verification remain
        # useful while the desktop/server is temporarily unavailable.
        if args.mode in ("push", "pull", "alter-product", "inspect-tally-product",
                         "verify-tally-products"):
            import urllib.request
            live_url = f"http://{instance.tally_host}:{instance.tally_port}"
            try:
                test_req = urllib.request.Request(
                    live_url,
                    data=b"<ENVELOPE><HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Collection</TYPE><ID>Company</ID></HEADER><BODY><DESC><STATICVARIABLES><SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT></STATICVARIABLES></DESC></BODY></ENVELOPE>",
                    headers={"Content-Type": "text/xml"}
                )
                with urllib.request.urlopen(test_req, timeout=5):
                    pass
            except Exception as e:
                raise SystemExit(f"[PAUSED] Real Live Tally server at {live_url} is offline: {e}")

        if args.mode == "verify-tally-products":
            from odoo.addons.tally_integration.services import tally_transport, tally_xml_builder, tally_xml_parser
            request = tally_xml_builder.build_collection_export(
                "StockItem", company_name=instance.tally_company,
                fetch_fields="NAME,GUID,ALTERID,PARENT,MAILINGNAME,MAILINGNAME.LIST,STANDARDCOST,STANDARDPRICE,CLOSINGBALANCE")
            endpoint = instance._tally_endpoint()
            response = tally_transport.post_xml(
                endpoint["url"], request, auth=endpoint["auth"],
                extra_headers=endpoint["headers"], verify=endpoint["verify"])
            parsed = tally_xml_parser.parse_stock_items_from_xml(
                tally_xml_parser.parse_tally_xml_root(response))
            rows = [row for row in parsed if row["name"].startswith(f"{PREFIX} ")]
            by_name = {row["name"]: row for row in rows}
            category_names = ("Hydraulics", "Electrical", "Industrial Consumables")
            mismatches = {}
            for index, (label, _hsn, cost, price) in enumerate(PRODUCTS, 1):
                name = f"{PREFIX} {index:02d} {label}"
                expected_row = {
                    "parent_group": f"{PREFIX} {category_names[(index - 1) % 3]}",
                    "part_no": f"{PREFIX}-P{index:02d}", "rate": cost,
                    "sale_price": price,
                }
                row = by_name.get(name)
                if (not row or any(row[key] != value for key, value in expected_row.items())):
                    mismatches[name] = {"expected": expected_row, "actual": row}
            result = {"expected_count": len(PRODUCTS), "actual_count": len(rows),
                      "mismatches": mismatches,
                      "ok": len(rows) == len(PRODUCTS) and not mismatches}
        elif args.mode == "restore-products":
            category_names = ("Hydraulics", "Electrical", "Industrial Consumables")
            restored = []
            for index, (label, _hsn, cost, price) in enumerate(PRODUCTS, 1):
                product_name = f"{PREFIX} {index:02d} {label}"
                product = env["product.product"].search([
                    ("name", "=", product_name),
                ], limit=1)
                category_name = f"{PREFIX} {category_names[(index - 1) % 3]}"
                category = env["product.category"].search([
                    ("name", "=", category_name),
                ], limit=1)
                if not product or not category:
                    raise SystemExit(f"Missing recovery product/category: {product_name} / {category_name}")
                product.product_tmpl_id.write({
                    "categ_id": category.id, "standard_price": cost, "list_price": price,
                })
                restored.append({"product": product_name, "category": category_name,
                                 "cost": cost, "price": price})
            cr.commit()
            result = {"restored_count": len(restored), "products": restored,
                      "pending_stock_item_queue": env["tally.sync.queue"].search_count([
                          ("instance_id", "=", instance.id), ("entity", "=", "stock_item"),
                          ("state", "=", "pending")])}
        elif args.mode == "inspect-tally-product":
            from odoo.addons.tally_integration.services import tally_transport, tally_xml_builder, tally_xml_parser
            request = tally_xml_builder.build_collection_export(
                "StockItem", company_name=instance.tally_company,
                fetch_fields="NAME,GUID,ALTERID,MAILINGNAME,MAILINGNAME.LIST,STANDARDCOST,STANDARDPRICE,CLOSINGBALANCE")
            endpoint = instance._tally_endpoint()
            response = tally_transport.post_xml(
                endpoint["url"], request, auth=endpoint["auth"],
                extra_headers=endpoint["headers"], verify=endpoint["verify"])
            parsed = tally_xml_parser.parse_stock_items_from_xml(
                tally_xml_parser.parse_tally_xml_root(response))
            matches = [row for row in parsed if row["name"] == args.product_name]
            result = {"product": args.product_name, "match_count": len(matches),
                      "tally": matches[0] if matches else None}
            if args.price is not None:
                result["matches_requested_price"] = bool(
                    matches and abs(matches[0]["sale_price"] - args.price) < 0.0001)
        elif args.mode == "set-odoo-price":
            if args.price is None:
                raise SystemExit("--price is required for set-odoo-price")
            product = env["product.product"].search([
                ("name", "=", args.product_name),
            ], limit=1)
            if not product:
                raise SystemExit(f"Product not found in Odoo: {args.product_name}")
            before = float(product.list_price)
            product.product_tmpl_id.write({"list_price": args.price})
            cr.commit()
            queue = env["tally.sync.queue"].search([
                ("instance_id", "=", instance.id), ("entity", "=", "stock_item"),
                ("odoo_model_name", "=", product._name), ("odoo_res_id", "=", product.id),
            ])
            result = {"product": product.name, "odoo_price_before": before,
                      "odoo_price_after": float(product.list_price),
                      "stock_item_queue_count": len(queue),
                      "queue_states": sorted(queue.mapped("state"))}
        elif args.mode == "inspect-product":
            product = env["product.product"].search([
                ("name", "=", args.product_name),
            ], limit=1)
            result = {
                "product": product.name if product else args.product_name,
                "exists": bool(product),
                "odoo_price": float(product.list_price) if product else None,
                "odoo_cost": float(product.standard_price) if product else None,
                "odoo_code": product.default_code if product else None,
                "product_count": env["product.product"].search_count([
                    ("name", "=like", f"{PREFIX} %")]),
                "queue_count": env["tally.sync.queue"].search_count([
                    ("instance_id", "=", instance.id)]),
                "mapping_count": env["tally.mapping"].search_count([
                    ("instance_id", "=", instance.id)]),
                "sync_log_error_count": env["tally.sync.log"].search_count([
                    ("instance_id", "=", instance.id), ("status", "=", "error")]),
            }
            if args.price is not None:
                result["matches_requested_price"] = bool(
                    product and abs(product.list_price - args.price) < 0.0001)
        elif args.mode == "alter-product":
            if args.price is None:
                raise SystemExit("--price is required for alter-product")
            from odoo.addons.tally_integration.services import tally_transport, tally_xml_builder
            product = env["product.product"].search([
                ("name", "=", args.product_name),
            ], limit=1)
            if not product:
                raise SystemExit(f"Product not found in Odoo: {args.product_name}")
            mapping = env["tally.mapping"].search([
                ("instance_id", "=", instance.id), ("entity", "=", "stock_item"),
                ("odoo_model_name", "=", product._name), ("odoo_res_id", "=", product.id),
            ], limit=1)
            if not mapping or not mapping.tally_guid:
                raise SystemExit(f"No Tally stock-item identity for: {args.product_name}")
            message = tally_xml_builder.build_stock_item_xml(
                name=product.name,
                base_uom=tally_xml_builder.normalize_tally_uom(product.uom_id.name),
                parent_group=product.categ_id.name,
                hsn_code=getattr(product, "l10n_in_hsn_code", None),
                standard_cost=product.standard_price,
                sale_price=args.price,
                guid=mapping.tally_guid,
                part_no=product.default_code,
                barcode=product.barcode,
                effective_date=args.effective_date,
            ).replace('ACTION="Create"', 'ACTION="Alter"', 1)
            payload = tally_xml_builder.wrap_import_envelope(
                [message], company_name=instance.tally_company)
            endpoint = instance._tally_endpoint()
            response = tally_transport.post_xml(
                endpoint["url"], payload, auth=endpoint["auth"],
                extra_headers=endpoint["headers"], verify=endpoint["verify"])
            result = tally_transport.parse_import_response(response)
            result.update({"product": product.name, "odoo_price_before_pull": product.list_price,
                           "requested_tally_price": args.price,
                           "effective_date": args.effective_date,
                           "tally_guid": mapping.tally_guid})
            if result["errors"] or not (result["altered"] or result["combined"]):
                raise SystemExit(json.dumps(result, indent=2))
        elif args.mode == "seed":
            seeded = seed(env, instance)
            cr.commit()
            result = snapshot(env, instance, args.expected)
            result["seeded"] = {key: len(value) if hasattr(value, "__len__") else value.id
                                for key, value in seeded.items()}
        elif args.mode == "push":
            instance._direct_dispatch_queue(limit=500, batch_size=20)
            cr.commit()
            result = snapshot(env, instance, args.expected)
        elif args.mode == "pull":
            pulled = instance._direct_pull(include_vouchers=True)
            cr.commit()
            result = {"pulled": pulled, "mapping_count": env["tally.mapping"].search_count([
                ("instance_id", "=", instance.id)]), "log_errors": env["tally.sync.log"].search_count([
                    ("instance_id", "=", instance.id), ("status", "=", "error")])}
        elif args.mode == "snapshot":
            result = snapshot(env, instance, args.expected)
        else:
            result = verify(env, instance, args.expected)
        rendered = json.dumps(result, indent=2, default=str)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered + "\n")
        print(rendered)


if __name__ == "__main__":
    main()
