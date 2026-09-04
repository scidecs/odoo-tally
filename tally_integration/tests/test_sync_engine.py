# -*- coding: utf-8 -*-
from unittest.mock import patch
import xml.etree.ElementTree as ET

from odoo.tests import TransactionCase, tagged

from ..services.sync_engine import SyncEngine


@tagged("post_install", "-at_install")
class TestTallySyncEngine(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Keep outbound routing deterministic even when the reusable validation
        # database contains instances created by a manual smoke test.
        cls.env["tally.instance"].search([
            ("company_id", "=", cls.env.company.id), ("active", "=", True),
        ]).write({"active": False})
        cls.instance = cls.env["tally.instance"].create({
            "name": "Automated Test Tally",
            "company_id": cls.env.company.id,
            "tally_company": "Automated Test Company",
            "auto_post": False,
            "direct_auto_pull": False,
        })

    def _config(self, entity, direction="tally_to_odoo", source="tally"):
        return self.env["tally.entity.config"].create({
            "instance_id": self.instance.id,
            "entity": entity,
            "direction": direction,
            "source_of_truth": source,
            "enabled": True,
        })

    def test_failed_batch_does_not_advance_watermark(self):
        config = self._config("uom")
        engine = SyncEngine(self.env, self.instance)
        with patch.object(engine, "_upsert_uom", side_effect=ValueError("invalid UoM")):
            result = engine.process_inbound_batch(
                "uom", [{"name": "Broken", "guid": "broken-uom", "alterid": 42}])
        self.assertEqual(result["errors"], 1)
        self.assertEqual(config.last_alterid, 0)

    def test_tally_origin_workflow_event_is_not_echoed(self):
        self._config("ledger", direction="both", source="bidirectional")
        partner = self.env["res.partner"].with_context(tally_no_sync=True).create({
            "name": "Inbound Party", "company_id": self.env.company.id,
        })
        mapping = self.env["tally.mapping"].create({
            "instance_id": self.instance.id,
            "entity": "ledger",
            "tally_guid": "11111111-1111-1111-1111-111111111111",
            "odoo_model_name": partner._name,
            "odoo_res_id": partner.id,
            "last_origin": "tally",
            "content_hash": "inbound",
        })
        self.assertFalse(self.env["tally.mapping"].register_outbound(
            self.instance, "ledger", partner._name, partner.id, "<changed/>",
            guid=mapping.tally_guid, allow_tally_origin=False))

    def test_outbound_guid_preserves_real_tally_identity(self):
        self._config("account_ledger", direction="both", source="odoo")
        account = self.env["account.account"].with_context(tally_no_sync=True).create({
            "name": "Mapped Account", "code": "991001", "account_type": "expense",
            "company_ids": [(6, 0, [self.env.company.id])],
        })
        real_guid = "33333333-3333-3333-3333-333333333333"
        self.env["tally.mapping"].create({
            "instance_id": self.instance.id, "entity": "account_ledger",
            "tally_guid": real_guid, "odoo_model_name": account._name,
            "odoo_res_id": account.id, "last_origin": "tally",
        })
        self.assertEqual(
            self.env["tally.mapping"].outbound_guid(
                self.instance, "account_ledger", account._name, account.id),
            real_guid,
        )

    def test_outbound_guid_upgrades_legacy_synthetic_identity(self):
        self._config("account_ledger", direction="both", source="odoo")
        account = self.env["account.account"].with_context(tally_no_sync=True).create({
            "name": "Legacy Mapped Account", "code": "991002", "account_type": "expense",
            "company_ids": [(6, 0, [self.env.company.id])],
        })
        self.env["tally.mapping"].create({
            "instance_id": self.instance.id, "entity": "account_ledger",
            "tally_guid": "odoo_account_legacy", "odoo_model_name": account._name,
            "odoo_res_id": account.id, "last_origin": "odoo",
        })
        guid = self.env["tally.mapping"].outbound_guid(
            self.instance, "account_ledger", account._name, account.id)
        self.assertFalse(guid.startswith("odoo_"))
        self.assertEqual(len(guid), 36)

    def test_odoo_owned_mapping_rejects_inbound_overwrite(self):
        self._config("uom", direction="both", source="odoo")
        uom = self.env["uom.uom"].create({"name": "Owned Unit", "rounding": 1.0})
        guid = "44444444-4444-4444-4444-444444444444"
        mapping = self.env["tally.mapping"].create({
            "instance_id": self.instance.id, "entity": "uom", "tally_guid": guid,
            "odoo_model_name": uom._name, "odoo_res_id": uom.id,
            "last_origin": "tally",
        })
        result = SyncEngine(self.env, self.instance).process_inbound_batch(
            "uom", [{"name": "Tally Rename", "guid": guid, "alterid": 7}])
        self.assertEqual(result["processed"], 0)
        self.assertEqual(uom.name, "Owned Unit")
        self.assertEqual(mapping.last_origin, "odoo")

    def test_inventory_invoice_does_not_duplicate_sales_ledger(self):
        self._config("sales", direction="both", source="tally")
        engine = SyncEngine(self.env, self.instance)
        move = engine._upsert_sales_invoice({
            "voucher_type": "Sales",
            "voucher_number": "TALLY-INV-001",
            "date": "2026-09-01",
            "party_ledger": "Invoice Test Customer",
            "guid": "22222222-2222-2222-2222-222222222222",
            "ledger_entries": [
                {"ledger": "Invoice Test Customer", "amount": 100.0},
                {"ledger": "Sales Account", "amount": -100.0},
            ],
            "inventory_entries": [
                {"item": "Invoice Test Item", "qty": 1.0, "rate": 100.0,
                 "amount": -100.0, "uom": "Units"},
            ],
        })
        self.assertEqual(move.amount_untaxed, 100.0)
        self.assertEqual(move.amount_total, 100.0)
        self.assertEqual(len(move.invoice_line_ids), 1)

    def test_opening_balance_creates_balanced_entry(self):
        self._config("opening_balance")
        move = SyncEngine(self.env, self.instance)._upsert_opening_balance({
            "name": "Opening Balance Test Expense",
            "parent": "Indirect Expenses",
            "opening_balance": 250.0,
            "guid": "55555555-5555-5555-5555-555555555555",
        })
        self.assertTrue(move)
        self.assertEqual(move.state, "draft")
        self.assertEqual(sum(move.line_ids.mapped("debit")), 250.0)
        self.assertEqual(sum(move.line_ids.mapped("credit")), 250.0)

    def test_direct_pull_routes_opening_balance_without_master_configs(self):
        self._config("opening_balance")
        payload = """<ENVELOPE><LEDGER NAME="Direct Opening Account">
          <PARENT>Indirect Expenses</PARENT><OPENINGBALANCE>75</OPENINGBALANCE>
          <GUID>66666666-6666-6666-6666-666666666666</GUID><ALTERID>61</ALTERID>
          </LEDGER></ENVELOPE>"""
        with patch(
            "odoo.addons.tally_integration.services.tally_transport.post_xml",
            return_value=payload,
        ):
            pulled = self.instance._direct_pull(include_vouchers=False)
        self.assertEqual(pulled, 1)
        move = self.env["account.move"].search([
            ("ref", "=", "TALLY-OPEN-66666666-6666-6666-6666-666666666666"),
        ])
        self.assertEqual(len(move), 1)

    def test_stock_journal_creates_internal_transfer(self):
        self._config("stock_journal")
        picking = SyncEngine(self.env, self.instance)._upsert_stock_journal({
            "voucher_number": "TALLY-STJ-001",
            "date": "2026-09-01",
            "inventory_entries": [
                {"item": "Transfer Test Item", "qty": -2.0, "godown": "Source Godown"},
                {"item": "Transfer Test Item", "qty": 2.0, "godown": "Destination Godown"},
            ],
        })
        self.assertEqual(picking.state, "draft")
        self.assertEqual(picking.picking_type_id.code, "internal")
        self.assertEqual(len(picking.move_ids), 1)
        self.assertEqual(picking.move_ids.product_uom_qty, 2.0)
        self.assertNotEqual(picking.location_id, picking.location_dest_id)

    def test_outbound_payment_builds_queue_item(self):
        self._config("receipt", direction="both", source="odoo")
        engine = SyncEngine(self.env, self.instance)
        journal = engine._get_or_create_journal("bank")
        partner = self.env["res.partner"].with_context(tally_no_sync=True).create({
            "name": "Payment Queue Customer", "company_id": self.env.company.id,
        })
        payment = self.env["account.payment"].with_context(tally_no_sync=True).create({
            "payment_type": "inbound",
            "partner_type": "customer",
            "partner_id": partner.id,
            "amount": 125.0,
            "date": "2026-09-01",
            "journal_id": journal.id,
        })
        payment._enqueue_tally_payment()
        queue = self.env["tally.sync.queue"].search([
            ("instance_id", "=", self.instance.id),
            ("odoo_model_name", "=", "account.payment"),
            ("odoo_res_id", "=", payment.id),
        ])
        self.assertEqual(len(queue), 1)
        self.assertIn("<VOUCHERTYPENAME>Receipt</VOUCHERTYPENAME>", queue.payload)
        self.assertIn("Payment Queue Customer", queue.payload)

    def test_outbound_master_hooks_enqueue_once(self):
        for entity in ("uom", "stock_group", "godown"):
            self._config(entity, direction="both", source="odoo")
        uom = self.env["uom.uom"].create({"name": "Cartons Test", "rounding": 0.01})
        category = self.env["product.category"].create({"name": "Roundtrip Category"})
        warehouse = self.env["stock.warehouse"].search([
            ("company_id", "=", self.env.company.id),
        ], limit=1)
        if not warehouse:
            warehouse = self.env["stock.warehouse"].create({
                "name": "Roundtrip Warehouse", "code": "RTW",
                "company_id": self.env.company.id,
            })
        location = self.env["stock.location"].create({
            "name": "Roundtrip Shelf", "location_id": warehouse.lot_stock_id.id,
            "usage": "internal", "company_id": self.env.company.id,
        })
        for entity, record in (("uom", uom), ("stock_group", category), ("godown", location)):
            queue = self.env["tally.sync.queue"].search([
                ("instance_id", "=", self.instance.id), ("entity", "=", entity),
                ("odoo_model_name", "=", record._name), ("odoo_res_id", "=", record.id),
            ])
            self.assertEqual(len(queue), 1)
        before = self.env["tally.sync.queue"].search_count([
            ("instance_id", "=", self.instance.id), ("entity", "=", "stock_group"),
            ("odoo_res_id", "=", category.id),
        ])
        category.write({"name": category.name})
        after = self.env["tally.sync.queue"].search_count([
            ("instance_id", "=", self.instance.id), ("entity", "=", "stock_group"),
            ("odoo_res_id", "=", category.id),
        ])
        self.assertEqual(before, after)

    def test_completed_internal_transfer_enqueues_stock_journal(self):
        self._config("stock_journal", direction="both", source="odoo")
        warehouse = self.env["stock.warehouse"].search([
            ("company_id", "=", self.env.company.id),
        ], limit=1)
        if not warehouse:
            warehouse = self.env["stock.warehouse"].create({
                "name": "Transfer Warehouse", "code": "TRW",
                "company_id": self.env.company.id,
            })
        source = self.env["stock.location"].with_context(tally_no_sync=True).create({
            "name": "Outbound Source", "location_id": warehouse.lot_stock_id.id,
            "usage": "internal", "company_id": self.env.company.id,
        })
        destination = self.env["stock.location"].with_context(tally_no_sync=True).create({
            "name": "Outbound Destination", "location_id": warehouse.lot_stock_id.id,
            "usage": "internal", "company_id": self.env.company.id,
        })
        product = self.env["product.product"].with_context(tally_no_sync=True).create({
            "name": "Outbound Transfer Product", "is_storable": True,
            "standard_price": 25.0, "company_id": self.env.company.id,
        })
        picking = self.env["stock.picking"].create({
            "picking_type_id": warehouse.int_type_id.id,
            "location_id": source.id, "location_dest_id": destination.id,
            "move_ids": [(0, 0, {
                "description_picking": product.name, "product_id": product.id,
                "product_uom_qty": 2.0, "product_uom": product.uom_id.id,
                "location_id": source.id, "location_dest_id": destination.id,
            })],
        })
        picking.action_confirm()
        picking.move_ids.quantity = 2.0
        picking.button_validate()
        queue = self.env["tally.sync.queue"].search([
            ("instance_id", "=", self.instance.id), ("entity", "=", "stock_journal"),
            ("odoo_res_id", "=", picking.id),
        ])
        self.assertEqual(len(queue), 1)
        self.assertIn("<VOUCHERTYPENAME>Stock Journal</VOUCHERTYPENAME>", queue.payload)
        self.assertIn("Outbound Source", queue.payload)
        self.assertIn("Outbound Destination", queue.payload)

    def test_outbound_invoice_and_return_payloads_balance_with_tax(self):
        engine = SyncEngine(self.env, self.instance)
        for entity in ("sales", "credit_note", "purchase", "debit_note"):
            self._config(entity, direction="both", source="odoo")
        income = engine._get_or_create_account("Roundtrip Sales", "income")
        expense = engine._get_or_create_account("Roundtrip Purchases", "expense")
        customer = engine._get_or_create_partner("Roundtrip Invoice Customer")
        vendor = engine._get_or_create_partner("Roundtrip Bill Vendor", is_supplier=True)
        product = self.env["product.product"].with_context(tally_no_sync=True).create({
            "name": "Taxed Roundtrip Product", "is_storable": True,
            "standard_price": 80.0, "list_price": 100.0,
            "property_account_income_id": income.id,
            "property_account_expense_id": expense.id,
            "company_id": self.env.company.id,
        })
        sales_tax = self.env["account.tax"].with_context(tally_no_sync=True).create({
            "name": "Output IGST 18%", "amount": 18.0, "amount_type": "percent",
            "type_tax_use": "sale", "company_id": self.env.company.id,
        })
        purchase_tax = self.env["account.tax"].with_context(tally_no_sync=True).create({
            "name": "Input IGST 18%", "amount": 18.0, "amount_type": "percent",
            "type_tax_use": "purchase", "company_id": self.env.company.id,
        })
        cases = (
            ("out_invoice", "sales", customer, income, sales_tax),
            ("out_refund", "credit_note", customer, income, sales_tax),
            ("in_invoice", "purchase", vendor, expense, purchase_tax),
            ("in_refund", "debit_note", vendor, expense, purchase_tax),
        )
        for index, (move_type, entity, partner, account, tax) in enumerate(cases, 1):
            journal = engine._get_or_create_journal(
                "sale" if move_type.startswith("out_") else "purchase")
            move = self.env["account.move"].create({
                "move_type": move_type, "partner_id": partner.id,
                "invoice_date": "2026-09-%02d" % index,
                "journal_id": journal.id,
                "invoice_line_ids": [(0, 0, {
                    "name": product.name, "product_id": product.id,
                    "quantity": 2.0, "price_unit": 100.0,
                    "account_id": account.id, "tax_ids": [(6, 0, [tax.id])],
                })],
            })
            move.action_post()
            queue = self.env["tally.sync.queue"].search([
                ("instance_id", "=", self.instance.id), ("entity", "=", entity),
                ("odoo_res_id", "=", move.id),
            ])
            self.assertEqual(len(queue), 1)
            root = ET.fromstring(queue.payload)
            ledger_total = sum(float(node.text or 0.0) for node in root.findall(".//ALLLEDGERENTRIES.LIST/AMOUNT"))
            inventory_total = sum(float(node.text or 0.0) for node in root.findall(".//ALLINVENTORYENTRIES.LIST/AMOUNT"))
            self.assertAlmostEqual(ledger_total + inventory_total, 0.0, places=2)
