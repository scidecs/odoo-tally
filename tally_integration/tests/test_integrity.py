# -*- coding: utf-8 -*-
"""Regression tests for data-integrity defects found against a live TallyPrime."""
import xml.etree.ElementTree as ET

from odoo.tests import TransactionCase, tagged

from ..services import tally_xml_builder as builder
from ..services import tally_xml_parser as parser
from ..services.sync_engine import SyncEngine, voucher_type_to_entity


@tagged("post_install", "-at_install")
class TestTallyParsing(TransactionCase):
    """Pure parsing rules (no database writes)."""

    def test_invoice_voucher_lines_are_not_doubled(self):
        # Tally repeats party/tax lines in LEDGERENTRIES next to ALLLEDGERENTRIES.
        root = parser.parse_tally_xml_root("""<ENVELOPE><VOUCHER VCHTYPE="Sales">
          <ALLLEDGERENTRIES.LIST><LEDGERNAME>Cust</LEDGERNAME><AMOUNT>-118.00</AMOUNT></ALLLEDGERENTRIES.LIST>
          <ALLLEDGERENTRIES.LIST><LEDGERNAME>Sales</LEDGERNAME><AMOUNT>100.00</AMOUNT></ALLLEDGERENTRIES.LIST>
          <ALLLEDGERENTRIES.LIST><LEDGERNAME>Output IGST 18%</LEDGERNAME><AMOUNT>18.00</AMOUNT></ALLLEDGERENTRIES.LIST>
          <LEDGERENTRIES.LIST><LEDGERNAME>Cust</LEDGERNAME><AMOUNT>-118.00</AMOUNT></LEDGERENTRIES.LIST>
          <LEDGERENTRIES.LIST><LEDGERNAME>Output IGST 18%</LEDGERNAME><AMOUNT>18.00</AMOUNT></LEDGERENTRIES.LIST>
        </VOUCHER></ENVELOPE>""")
        v = parser.parse_vouchers_from_xml(root)[0]
        self.assertEqual(len(v["ledger_entries"]), 3)
        self.assertAlmostEqual(sum(e["amount"] for e in v["ledger_entries"]), 0.0)

    def test_stock_journal_lines_are_not_tripled(self):
        root = parser.parse_tally_xml_root("""<ENVELOPE><VOUCHER VCHTYPE="Stock Journal">
          <ALLINVENTORYENTRIES.LIST><STOCKITEMNAME>X</STOCKITEMNAME><ACTUALQTY>1 Nos</ACTUALQTY><AMOUNT>10</AMOUNT></ALLINVENTORYENTRIES.LIST>
          <ALLINVENTORYENTRIES.LIST><STOCKITEMNAME>X</STOCKITEMNAME><ACTUALQTY>-1 Nos</ACTUALQTY><AMOUNT>-10</AMOUNT></ALLINVENTORYENTRIES.LIST>
          <INVENTORYENTRIESIN.LIST><STOCKITEMNAME>X</STOCKITEMNAME><ACTUALQTY>1 Nos</ACTUALQTY><AMOUNT>-10</AMOUNT></INVENTORYENTRIESIN.LIST>
          <INVENTORYENTRIESOUT.LIST><STOCKITEMNAME>X</STOCKITEMNAME><ACTUALQTY>1 Nos</ACTUALQTY><AMOUNT>10</AMOUNT></INVENTORYENTRIESOUT.LIST>
        </VOUCHER></ENVELOPE>""")
        v = parser.parse_vouchers_from_xml(root)[0]
        self.assertEqual([e["qty"] for e in v["inventory_entries"]], [-1.0, 1.0])

    def test_party_under_custom_subgroup_stays_a_party(self):
        tree = parser.build_group_tree([
            {"name": "Debtors - North", "parent": "Sundry Debtors"},
            {"name": "Sundry Debtors", "parent": "Primary"},
            {"name": "Indirect Expenses", "parent": "Primary"},
        ])
        ledgers = [
            {"name": "North Customer", "parent": "Debtors - North", "tax_type": "Others"},
            {"name": "Processing Fees", "parent": "Indirect Expenses"},
        ]
        parties = [l["name"] for l in parser.filter_ledgers_for_entity([dict(l) for l in ledgers], "ledger", tree)]
        accounts = [l["name"] for l in parser.filter_ledgers_for_entity([dict(l) for l in ledgers], "account_ledger", tree)]
        self.assertEqual(parties, ["North Customer"])
        self.assertEqual(accounts, ["Processing Fees"])

    def test_non_accounting_voucher_types_are_not_imported(self):
        self.assertIsNone(voucher_type_to_entity("Sales Order"))
        self.assertIsNone(voucher_type_to_entity("Purchase Order"))
        self.assertIsNone(voucher_type_to_entity("Delivery Note"))
        self.assertIsNone(voucher_type_to_entity("Memorandum"))
        parents = {"tax invoice": "sales", "gst sales order": "sales order"}
        self.assertEqual(voucher_type_to_entity("Tax Invoice", parents), "sales")
        self.assertIsNone(voucher_type_to_entity("GST Sales Order", parents))
        self.assertEqual(voucher_type_to_entity("Credit Note"), "credit_note")

    def test_rename_alters_existing_master(self):
        root = ET.fromstring(builder.build_party_ledger_xml("New Name", guid="g", old_name="Old Name"))
        ledger = root.find("LEDGER")
        self.assertEqual(ledger.get("NAME"), "Old Name")
        self.assertEqual(ledger.get("ACTION"), "Alter")
        self.assertEqual(ledger.findtext("NAME.LIST/NAME"), "New Name")

    def test_known_voucher_is_altered_by_tally_number(self):
        import datetime
        root = ET.fromstring(builder.build_voucher_xml(
            "Sales", "INV/2026/001", datetime.date(2026, 9, 1), "Cust",
            ledger_entries=[{"ledger": "Cust", "amount": -1.0}, {"ledger": "Sales", "amount": 1.0}],
            guid="g", alter_address={"voucher_number": "17", "date": datetime.date(2026, 9, 1),
                                     "voucher_type": "Sales"}))
        voucher = root.find("VOUCHER")
        self.assertEqual(voucher.get("ACTION"), "Alter")
        self.assertEqual(voucher.get("TAGVALUE"), "17")
        self.assertEqual(voucher.get("DATE"), "01-Sep-2026")

    def test_collection_export_always_fetches_identity(self):
        xml = builder.build_collection_export("Ledger", company_name="C")
        self.assertIn("RemoteAltGUID", xml)
        self.assertIn("AlterID", xml)
        self.assertIn("GUID", xml)


@tagged("post_install", "-at_install")
class TestTallyIntegrity(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["tally.instance"].search([("active", "=", True)]).write({"active": False})
        cls.instance = cls.env["tally.instance"].create({
            "name": "Integrity Test Tally",
            "company_id": cls.env.company.id,
            "tally_company": "Integrity Co",
            "auto_post": True,
            "direct_auto_pull": False,
            "tally_ledger_index": '{"integrity customer": {"party": true, "tax": false, "chain": ["sundry debtors"], "parent": "Sundry Debtors"},'
                                  ' "integrity vendor": {"party": true, "tax": false, "chain": ["sundry creditors"], "parent": "Sundry Creditors"},'
                                  ' "output cgst 9%": {"party": false, "tax": true, "chain": ["duties & taxes"], "parent": "Duties & Taxes"},'
                                  ' "output sgst 9%": {"party": false, "tax": true, "chain": ["duties & taxes"], "parent": "Duties & Taxes"},'
                                  ' "processing fees": {"party": false, "tax": false, "chain": ["indirect incomes"], "parent": "Indirect Incomes"},'
                                  ' "round off": {"party": false, "tax": false, "chain": ["indirect expenses"], "parent": "Indirect Expenses"},'
                                  ' "sales account": {"party": false, "tax": false, "chain": ["sales accounts"], "parent": "Sales Accounts"},'
                                  ' "rent": {"party": false, "tax": false, "chain": ["indirect expenses"], "parent": "Indirect Expenses"},'
                                  ' "hdfc bank": {"party": false, "tax": false, "chain": ["bank accounts"], "parent": "Bank Accounts"}}',
        })
        for entity in ("ledger", "sales", "journal", "receipt", "payment", "opening_balance", "account_ledger"):
            cls.env["tally.entity.config"].create({
                "instance_id": cls.instance.id, "entity": entity, "enabled": True,
                "direction": "both", "source_of_truth": "bidirectional",
            })

    def _engine(self):
        return SyncEngine(self.env, self.instance)

    def _sales(self, guid, alterid, amount=118.0, number="1", extra=None, cancelled=False):
        base = amount / 1.18
        entries = [
            {"ledger": "Integrity Customer", "amount": -amount},
            {"ledger": "Sales Account", "amount": round(base, 2)},
            {"ledger": "Output CGST 9%", "amount": round(base * 0.09, 2)},
            {"ledger": "Output SGST 9%", "amount": round(base * 0.09, 2)},
        ] + (extra or [])
        return {"voucher_type": "Sales", "voucher_number": number, "date": "2026-09-01",
                "party_ledger": "Integrity Customer", "guid": guid, "alterid": str(alterid),
                "ledger_entries": entries, "inventory_entries": [], "is_cancelled": cancelled}

    def _move_for(self, guid):
        m = self.env["tally.mapping"].search([("instance_id", "=", self.instance.id), ("tally_guid", "=", guid)])
        return self.env[m.odoo_model_name].browse(m.odoo_res_id)

    def test_tax_ledger_detection_uses_whole_words(self):
        engine = self._engine()
        self.instance.tally_ledger_index = False
        engine.ledger_index = {}
        self.assertFalse(engine._is_tax_ledger("Processing Fees"))
        self.assertFalse(engine._is_tax_ledger("Excess and Shortage"))
        self.assertFalse(engine._is_tax_ledger("Renovation Charges"))
        self.assertTrue(engine._is_tax_ledger("Output CGST 9%"))
        self.assertTrue(engine._is_tax_ledger("TDS Payable"))

    def test_charge_and_round_off_lines_keep_tally_sign(self):
        extra = [{"ledger": "Processing Fees", "amount": 50.0}, {"ledger": "Round Off", "amount": 0.4}]
        rec = self._sales("11111111-aaaa-0000-0000-000000000001", 10, amount=168.4, extra=extra)
        rec["ledger_entries"][1]["amount"] = 100.0
        rec["ledger_entries"][2]["amount"] = 9.0
        rec["ledger_entries"][3]["amount"] = 9.0
        self._engine().process_vouchers([rec])
        move = self._move_for(rec["guid"])
        self.assertAlmostEqual(move.amount_total, 168.4, places=2)
        names = move.invoice_line_ids.mapped("name")
        self.assertIn("Processing Fees", names)
        self.assertIn("Round Off", names)
        detail = [(l.name, l.price_unit, l.tax_ids.mapped(lambda t: (t.name, t.amount, t.amount_type)),
                   l.price_subtotal, l.price_total) for l in move.invoice_line_ids]
        self.assertNotIn("Tally total reconciliation", names, detail)
        tax_lines = move.line_ids.filtered(lambda l: l.tax_line_id)
        self.assertEqual(set(tax_lines.account_id.mapped("name")), {"Output CGST 9%", "Output SGST 9%"},
                         [(l.name, l.account_id.name, l.tax_line_id.name, l.balance) for l in move.line_ids]
                         + [(t.name, [(r.repartition_type, r.document_type, r.account_id.name) for r in t.repartition_line_ids])
                            for t in move.line_ids.tax_line_id])
        fees = move.invoice_line_ids.filtered(lambda l: l.name == "Processing Fees")
        self.assertAlmostEqual(fees.price_subtotal, 50.0)
        self.assertFalse(self.env["account.tax"].search([("name", "=", "Processing Fees")]))

    def test_opening_balance_debit_is_negative_in_tally(self):
        move = self._engine()._upsert_opening_balance({
            "name": "Integrity Customer", "parent": "Sundry Debtors",
            "group_chain": ["sundry debtors"], "opening_balance": -1000.0, "guid": "ob-guid"})
        receivable = move.line_ids.filtered(lambda l: l.account_id.account_type == "asset_receivable")
        self.assertEqual(receivable.debit, 1000.0)
        self.assertEqual(receivable.credit, 0.0)

    def test_journals_with_same_narration_are_not_merged(self):
        def jv(guid, alterid, number):
            return {"voucher_type": "Journal", "voucher_number": number, "date": "2026-09-01",
                    "guid": guid, "alterid": str(alterid), "narration": "Being salary paid",
                    "ledger_entries": [{"ledger": "Rent", "amount": -10.0},
                                       {"ledger": "HDFC Bank", "amount": 10.0}]}
        self._engine().process_vouchers([jv("jv-guid-1", 21, "5"), jv("jv-guid-2", 22, "6")])
        self.assertNotEqual(self._move_for("jv-guid-1"), self._move_for("jv-guid-2"))

    def test_direct_expense_payment_is_a_journal_not_a_partner_payment(self):
        rec = {"voucher_type": "Payment", "voucher_number": "9", "date": "2026-09-01",
               "party_ledger": "Rent", "guid": "pay-rent", "alterid": "30",
               "ledger_entries": [{"ledger": "Rent", "amount": -500.0},
                                  {"ledger": "HDFC Bank", "amount": 500.0}]}
        self._engine().process_vouchers([rec])
        record = self._move_for("pay-rent")
        self.assertEqual(record._name, "account.move")
        self.assertFalse(self.env["res.partner"].search([("name", "=", "Rent")]))

    def test_simple_receipt_is_a_payment_with_party_amount(self):
        rec = {"voucher_type": "Receipt", "voucher_number": "3", "date": "2026-09-01",
               "party_ledger": "Integrity Customer", "guid": "rcpt-1", "alterid": "31",
               "ledger_entries": [{"ledger": "Integrity Customer", "amount": 700.0},
                                  {"ledger": "HDFC Bank", "amount": -700.0}]}
        self._engine().process_vouchers([rec])
        payment = self._move_for("rcpt-1")
        self.assertEqual(payment._name, "account.payment")
        self.assertEqual(payment.payment_type, "inbound")
        self.assertEqual(payment.amount, 700.0)

    def test_echo_of_odoo_push_is_bound_not_imported(self):
        partner = self.env["res.partner"].with_context(tally_no_sync=True).create({"name": "Pushed Party"})
        mapping = self.env["tally.mapping"].create({
            "instance_id": self.instance.id, "entity": "ledger", "remote_id": "our-remote-id",
            "tally_name": "Pushed Party", "odoo_model_name": partner._name,
            "odoo_res_id": partner.id, "last_origin": "odoo"})
        result = self._engine().process_inbound_batch("ledger", [{
            "name": "Pushed Party", "parent": "Sundry Debtors", "guid": "tally-real-guid",
            "alterid": "500", "remote_alt_guid": "our-remote-id"}])
        self.assertEqual(result["processed"], 0)
        self.assertEqual(mapping.tally_guid, "tally-real-guid")
        self.assertEqual(mapping.tally_alterid, 500)
        self.assertEqual(self.env["res.partner"].search_count([("name", "=", "Pushed Party")]), 1)

    def test_known_revision_is_skipped_newer_revision_updates_posted_invoice(self):
        guid = "inv-rev-guid"
        engine = self._engine()
        engine.process_vouchers([self._sales(guid, 40)])
        move = self._move_for(guid)
        self.assertEqual(move.state, "posted")
        self.assertAlmostEqual(move.amount_total, 118.0)
        # Same revision again (e.g. read-back): nothing changes.
        self.assertEqual(engine.process_vouchers([self._sales(guid, 40, amount=236.0)])["sales"]["processed"], 0)
        self.assertAlmostEqual(move.amount_total, 118.0)
        # Edited in Tally: same Odoo invoice is amended and re-posted.
        self._engine().process_vouchers([self._sales(guid, 41, amount=236.0)])
        self.assertEqual(self._move_for(guid), move)
        self.assertEqual(move.state, "posted")
        self.assertAlmostEqual(move.amount_total, 236.0)

    def test_cancelled_in_tally_cancels_in_odoo(self):
        guid = "inv-cancel-guid"
        self._engine().process_vouchers([self._sales(guid, 50)])
        move = self._move_for(guid)
        self._engine().process_vouchers([self._sales(guid, 51, cancelled=True)])
        self.assertEqual(move.state, "cancel")

    def test_rename_in_tally_updates_same_partner(self):
        engine = self._engine()
        engine.process_inbound_batch("ledger", [{"name": "Old Party Name", "parent": "Sundry Debtors",
                                                 "guid": "party-rename", "alterid": "60"}])
        partner = self._move_for("party-rename")
        self._engine().process_inbound_batch("ledger", [{"name": "New Party Name", "parent": "Sundry Debtors",
                                                         "guid": "party-rename", "alterid": "61"}])
        self.assertEqual(self._move_for("party-rename"), partner)
        self.assertEqual(partner.name, "New Party Name")

    def test_odoo_rename_of_linked_party_alters_in_tally(self):
        partner = self.env["res.partner"].with_context(tally_no_sync=True).create(
            {"name": "Linked Party", "customer_rank": 1})
        self.env["tally.mapping"].create({
            "instance_id": self.instance.id, "entity": "ledger", "tally_guid": "linked-guid",
            "tally_name": "Linked Party", "odoo_model_name": partner._name,
            "odoo_res_id": partner.id, "last_origin": "tally"})
        partner.with_context(tally_no_sync=False).write({"name": "Linked Party Pvt Ltd"})
        queue = self.env["tally.sync.queue"].search([
            ("instance_id", "=", self.instance.id), ("odoo_res_id", "=", partner.id), ("entity", "=", "ledger")])
        self.assertEqual(len(queue), 1)
        ledger = ET.fromstring(queue.payload).find(".//LEDGER")
        self.assertEqual(ledger.get("NAME"), "Linked Party")
        self.assertEqual(ledger.get("ACTION"), "Alter")
        self.assertEqual(ledger.findtext("NAME.LIST/NAME"), "Linked Party Pvt Ltd")

    def test_rank_change_does_not_push_party(self):
        partner = self.env["res.partner"].with_context(tally_no_sync=True).create({"name": "Quiet Party"})
        partner.with_context(tally_no_sync=False).write({"customer_rank": 3})
        self.assertFalse(self.env["tally.sync.queue"].search_count([("odoo_res_id", "=", partner.id),
                                                                      ("entity", "=", "ledger")]))

    def test_posting_unchanged_tally_invoice_is_not_written_back(self):
        self.instance.auto_post = False
        guid = "inv-fp-guid"
        self._engine().process_vouchers([self._sales(guid, 70)])
        move = self._move_for(guid)
        self.assertEqual(move.state, "draft")
        move.action_post()
        self.assertFalse(self.env["tally.sync.queue"].search_count([
            ("odoo_model_name", "=", "account.move"), ("odoo_res_id", "=", move.id)]))

    def test_pushed_invoice_reset_to_draft_cancels_in_tally(self):
        engine = self._engine()
        partner = engine._get_or_create_partner("Integrity Customer")
        account = engine._get_or_create_account("Sales Account", "income")
        move = self.env["account.move"].create({
            "move_type": "out_invoice", "partner_id": partner.id, "invoice_date": "2026-09-01",
            "invoice_line_ids": [(0, 0, {"name": "Svc", "quantity": 1, "price_unit": 100.0,
                                         "account_id": account.id, "tax_ids": [(6, 0, [])]})]})
        move.action_post()
        mapping = self.env["tally.mapping"].for_record(self.instance, "sales", move._name, move.id)
        self.assertTrue(mapping.remote_id)
        # Simulate Tally accepting it (identity bound after push).
        self.env["tally.sync.queue"].search([("odoo_res_id", "=", move.id)]).write({"state": "acked"})
        mapping.bind_identity({"guid": "pushed-guid", "alterid": "90", "voucher_number": "44",
                               "voucher_type": "Sales", "date": "2026-09-01"})
        move.button_draft()
        cancel = self.env["tally.sync.queue"].search([
            ("odoo_res_id", "=", move.id), ("state", "=", "pending")])
        self.assertEqual(len(cancel), 1)
        voucher = ET.fromstring(cancel.payload).find(".//VOUCHER")
        self.assertEqual(voucher.get("ACTION"), "Cancel")
        # Odoo-created: addressed by REMOTEID, never by the (non-unique) number.
        self.assertEqual(voucher.get("REMOTEID"), mapping.remote_id)
        self.assertIsNone(voucher.get("TAGVALUE"))
        # Re-post: the same Tally voucher is re-sent under its REMOTEID (Tally alters
        # and restores it), never created again.
        move.action_post()
        repost = self.env["tally.sync.queue"].search([
            ("odoo_res_id", "=", move.id), ("state", "=", "pending")])
        voucher = ET.fromstring(repost.payload).find(".//VOUCHER")
        self.assertEqual(voucher.get("REMOTEID"), mapping.remote_id)
        self.assertIsNone(voucher.get("TAGVALUE"))

    def test_tally_voucher_edited_in_odoo_is_addressed_by_verified_number(self):
        self._engine().process_vouchers([self._sales("typed-in-tally", 80, number="17")])
        move = self._move_for("typed-in-tally")
        self.instance.entity_config_ids.filtered(lambda c: c.entity == "sales").source_of_truth = "bidirectional"
        move.with_context(tally_no_sync=False).button_draft()
        move.invoice_line_ids[0].price_unit = 150.0
        move.action_post()
        item = self.env["tally.sync.queue"].search([("odoo_res_id", "=", move.id), ("state", "=", "pending")])
        voucher = ET.fromstring(item.payload).find(".//VOUCHER")
        self.assertEqual(voucher.get("ACTION"), "Alter")
        self.assertEqual(voucher.get("TAGVALUE"), "17")
        verify, expected = self.instance._voucher_address_check(item)
        self.assertIn("$VoucherNumber", verify)
        self.assertEqual(expected, "typed-in-tally")
        # Two vouchers (e.g. Sales 17 and Journal 17) on that date: refuse to send.
        self.assertFalse(self.instance._voucher_address_ok(
            "<GUID>typed-in-tally</GUID><GUID>other-type-guid</GUID>", expected))
        self.assertTrue(self.instance._voucher_address_ok("<GUID>typed-in-tally</GUID>", expected))

    def test_shared_partner_goes_to_every_company_tally(self):
        company_b = self.env["res.company"].create({"name": "Integrity Company B"})
        instance_b = self.env["tally.instance"].create({
            "name": "Company B Tally", "company_id": company_b.id, "tally_company": "B Co"})
        self.env["tally.entity.config"].create({
            "instance_id": instance_b.id, "entity": "ledger", "enabled": True,
            "direction": "both", "source_of_truth": "bidirectional"})
        partner = self.env["res.partner"].create({"name": "Shared Group Customer", "customer_rank": 1,
                                                  "company_id": False})
        instances = self.env["tally.sync.queue"].search([
            ("odoo_res_id", "=", partner.id), ("entity", "=", "ledger")]).mapped("instance_id")
        self.assertEqual(instances, self.instance | instance_b)
        own = self.env["res.partner"].create({"name": "Company B Only Customer", "customer_rank": 1,
                                              "company_id": company_b.id})
        instances = self.env["tally.sync.queue"].search([
            ("odoo_res_id", "=", own.id), ("entity", "=", "ledger")]).mapped("instance_id")
        self.assertEqual(instances, instance_b)

    def test_gst_components_never_collapse(self):
        engine = self._engine()
        cgst = engine._find_or_create_tax("Output CGST 9%", tax_type="sale")
        sgst = engine._find_or_create_tax("Output SGST 9%", tax_type="sale")
        igst = engine._find_or_create_tax("Output IGST 18%", tax_type="sale")
        self.assertEqual(len(cgst | sgst | igst), 3)
        # Import mode: every Tally tax ledger keeps a tax (and account) of its own.
        self.assertNotIn(engine._find_or_create_tax("SGST @ 9%", tax_type="sale"), cgst | sgst | igst)
        # Map-to-existing-CoA mode: reuse the company's tax of the same component.
        self.instance.coa_mode = "map"
        self.assertEqual(engine._find_or_create_tax("SGST 9%", tax_type="sale"), sgst)
        self.assertEqual(engine._find_or_create_tax("CGST 9%", tax_type="sale"), cgst)
        # GST must post to its own Duties & Taxes account, never onto Sales.
        for tax in (cgst, sgst, igst):
            accounts = tax.invoice_repartition_line_ids.filtered(
                lambda l: l.repartition_type == "tax").account_id
            self.assertTrue(accounts)
            self.assertIn(accounts.account_type, ("liability_current", "asset_current"))


    def test_second_company_imports_with_its_own_account_codes(self):
        company_b = self.env["res.company"].create({"name": "Codes Company B"})
        self.env["account.chart.template"].try_loading("generic_coa", company_b, install_demo=False)
        instance_b = self.env["tally.instance"].create({
            "name": "Codes B Tally", "company_id": company_b.id, "tally_company": "B", "auto_post": True,
            "tally_ledger_index": self.instance.tally_ledger_index})
        self.env["tally.entity.config"].create({
            "instance_id": instance_b.id, "entity": "sales", "enabled": True,
            "direction": "both", "source_of_truth": "bidirectional"})
        self._engine().process_vouchers([self._sales("codes-a", 90)])
        SyncEngine(self.env, instance_b).process_vouchers([self._sales("codes-b", 91)])
        move_b = self.env["account.move"].browse(self.env["tally.mapping"].search([
            ("instance_id", "=", instance_b.id), ("tally_guid", "=", "codes-b")]).odoo_res_id)
        self.assertEqual(move_b.company_id, company_b)
        self.assertEqual(move_b.state, "posted")
        self.assertTrue(all(company_b in (l.account_id.company_ids if "company_ids" in l.account_id._fields
                                          else l.account_id.company_id) for l in move_b.line_ids))
