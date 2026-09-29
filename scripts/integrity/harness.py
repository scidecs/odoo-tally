# -*- coding: utf-8 -*-
"""Live Odoo <-> TallyPrime integrity harness (run inside `odoo-bin shell`).

Environment variables:
  SCENARIO      s1 | s2 | s3 | s4
  TALLY_CO      Tally company name (s4: two names separated by '|')
  REPORT        path of the JSON report to write
"""
import datetime
import json
import os
import re
import traceback

from odoo.addons.tally_integration.services import tally_transport as T
from odoo.addons.tally_integration.services import tally_xml_builder as B
from odoo.addons.tally_integration.services import tally_xml_parser as P

TALLY_HOST = os.environ.get("TALLY_HOST", "127.0.0.1")
D1 = datetime.date(2026, 9, 1)
D2 = datetime.date(2026, 9, 2)
D_AUG31 = datetime.date(2026, 8, 31)
D_OCT31 = datetime.date(2026, 10, 31)
PERIOD_END = datetime.date(2027, 3, 31)
REPORT = {"scenario": os.environ.get("SCENARIO"), "steps": [], "failures": []}
ACCOUNTING_TYPES = ("Sales", "Purchase", "Receipt", "Payment", "Journal", "Contra",
                    "Credit Note", "Debit Note")


# ----------------------------------------------------------------- utilities
def log(msg):
    print("[harness] %s" % msg, flush=True)


def tally_post(xml, company=None):
    return T.post_xml("http://%s:9000" % TALLY_HOST, xml, timeout=300)


def tally_import(messages, company, report_type="Vouchers"):
    raw = tally_post(B.wrap_import_envelope(messages, company_name=company, report_type=report_type))
    res = T.parse_import_response(raw)
    if res["errors"] or res["line_error"]:
        raise AssertionError("Tally rejected import: %s" % res)
    return res


def tally_vouchers(company, formula=None):
    return P.parse_vouchers_from_xml(P.parse_tally_xml_root(tally_post(
        B.build_voucher_collection_export(company_name=company, formula=formula))))


def tally_ledgers(company):
    xml = B.build_collection_export("Ledger", company_name=company,
                                    fetch_fields="Name,Parent,OpeningBalance,ClosingBalance,GUID,AlterID")
    root = P.parse_tally_xml_root(tally_post(xml))
    out = []
    for l in root.iter("LEDGER"):
        name = l.get("NAME") or (l.findtext("NAME") or "").strip()
        if not name:
            continue
        def num(tag):
            m = re.search(r"-?\d+(?:\.\d+)?", l.findtext(tag) or "")
            return float(m.group(0)) if m else 0.0
        out.append({"name": name, "parent": (l.findtext("PARENT") or "").strip(),
                    "guid": (l.findtext("GUID") or "").strip(),
                    "opening": num("OPENINGBALANCE"), "closing": num("CLOSINGBALANCE")})
    return out


def sync(inst, rounds=3):
    """Push everything queued, then pull; repeat until the queue is drained."""
    for _ in range(rounds):
        inst._direct_dispatch_queue(limit=500)
        env.cr.commit()
        pending = env["tally.sync.queue"].search([("instance_id", "=", inst.id),
                                                   ("state", "in", ("pending", "sent"))])
        failed = env["tally.sync.queue"].search([("instance_id", "=", inst.id), ("state", "=", "failed")])
        if not pending:
            break
    inst._direct_pull()
    env.cr.commit()
    failed = env["tally.sync.queue"].search([("instance_id", "=", inst.id), ("state", "=", "failed")])
    return failed


# ----------------------------------------------------------------- audit
def odoo_balance(company, account=None, partner=None):
    domain = [("company_id", "=", company.id), ("parent_state", "=", "posted"),
              ("date", "<=", PERIOD_END)]
    if account:
        domain.append(("account_id", "in", account.ids))
    if partner:
        domain += [("partner_id", "child_of", partner.commercial_partner_id.id),
                   ("account_id.account_type", "in", ("asset_receivable", "liability_payable"))]
    return round(sum(env["account.move.line"].search(domain).mapped("balance")), 2)


def resolve(inst, ledger):
    """Tally ledger -> ('partner', rec) | ('account', rec) | (None, None)."""
    Mapping = env["tally.mapping"]
    company = inst.company_id
    for entity, model in (("ledger", "res.partner"), ("account_ledger", "account.account")):
        m = Mapping.search([("instance_id", "=", inst.id), ("entity", "=", entity),
                            "|", ("tally_guid", "=", ledger["guid"]), ("tally_name", "=", ledger["name"])], limit=1)
        if m and m.odoo_model_name == model:
            rec = env[model].browse(m.odoo_res_id).exists()
            if rec:
                return ("partner" if model == "res.partner" else "account"), rec
    tax = env["account.tax"].search([("name", "=", ledger["name"]), ("company_id", "=", company.id)], limit=1)
    if tax:
        acc = tax.invoice_repartition_line_ids.filtered(lambda l: l.repartition_type == "tax").account_id[:1]
        if acc:
            return "account", acc
    Account = env["account.account"]
    cdom = [("company_ids", "in", company.ids)] if "company_ids" in Account._fields else [("company_id", "=", company.id)]
    acc = Account.search(cdom + [("name", "=", ledger["name"])], limit=1)
    if acc:
        return "account", acc
    journal = env["account.journal"].search([("company_id", "=", company.id), ("name", "=", ledger["name"])], limit=1)
    if journal.default_account_id:
        return "account", journal.default_account_id
    partner = env["res.partner"].search([("name", "=", ledger["name"])], limit=1)
    if partner:
        return "partner", partner
    return None, None


def audit(inst, label, expect_clean=True):
    """Compare every Tally ledger closing balance with Odoo."""
    company = inst.company_id
    tco = inst.tally_company
    ledgers = tally_ledgers(tco)
    issues = []
    per_account = {}
    covered_accounts = env["account.account"]
    partner_total_t = partner_total_o = 0.0
    all_vouchers = tally_vouchers(tco)
    for led in ledgers:
        kind, rec = resolve(inst, led)
        expected = round(-led["closing"], 2)  # Tally: debit negative; Odoo: debit positive
        if led["parent"].lower() in ("primary", "") and "profit" in led["name"].lower():
            # Tally's closing on this ledger includes the computed current-year profit;
            # compare only what is actually posted to it.
            posted = sum(float(e["amount"] or 0) for v in all_vouchers if not v.get("is_cancelled")
                         for e in v["ledger_entries"] if e["ledger"] == led["name"])
            expected = round(-(led["opening"] + posted), 2)
        if kind == "partner":
            got = odoo_balance(company, partner=rec)
            partner_total_t += expected
            partner_total_o += got
            if abs(got - expected) > 0.01:
                issues.append("party %s: Tally %.2f vs Odoo %.2f" % (led["name"], expected, got))
        elif kind == "account":
            per_account.setdefault(rec.id, [rec, 0.0, []])
            per_account[rec.id][1] += expected
            per_account[rec.id][2].append(led["name"])
            covered_accounts |= rec
        elif abs(expected) > 0.005:
            issues.append("ledger %s (%.2f) has no Odoo counterpart" % (led["name"], expected))
    # Odoo 18+ books payments on "Outstanding Receipts/Payments" until the bank
    # statement is matched; Tally debits the bank ledger straight away. Compare
    # all bank/cash ledgers together with those outstanding accounts.
    bank_journals = env["account.journal"].search([("company_id", "=", company.id), ("type", "in", ("bank", "cash"))])
    outstanding = (bank_journals.inbound_payment_method_line_ids.payment_account_id
                   | bank_journals.outbound_payment_method_line_ids.payment_account_id)
    payments = env["account.payment"].search([("company_id", "=", company.id)])
    if "outstanding_account_id" in payments._fields:
        outstanding |= payments.outstanding_account_id
    for fname in ("account_journal_payment_debit_account_id", "account_journal_payment_credit_account_id"):
        if fname in company._fields:
            outstanding |= company[fname]
    bank_accounts = bank_journals.default_account_id
    bank_bucket = [env["account.account"], 0.0, []]
    for key in list(per_account):
        rec, expected, names = per_account[key]
        if rec in bank_accounts or rec in outstanding:
            bank_bucket[0] |= rec
            bank_bucket[1] += expected
            bank_bucket[2] += names
            del per_account[key]
    if bank_bucket[2]:
        bank_bucket[0] |= outstanding
        covered_accounts |= outstanding
        per_account["bank"] = bank_bucket
    for key, (rec, expected, names) in per_account.items():
        got = odoo_balance(company, account=rec)
        if key == "bank" and abs(got - round(expected, 2)) > 0.01:
            # Itemise per bank journal: default account + its payments' outstanding lines.
            for led in [l for l in ledgers if l["name"] in names]:
                j = env["account.journal"].search([("company_id", "=", company.id), ("name", "=", led["name"])], limit=1) \
                    or env["account.journal"].search([("company_id", "=", company.id), ("default_account_id.name", "=", led["name"])], limit=1)
                pays = env["account.payment"].search([("journal_id", "=", j.id), ("state", "not in", ("draft", "cancel"))]) if j else env["account.payment"]
                odoo_j = odoo_balance(company, account=j.default_account_id) + round(sum(
                    (p.amount_signed if "amount_signed" in p._fields else (p.amount if p.payment_type == "inbound" else -p.amount))
                    for p in pays), 2)
                if abs(odoo_j + led["closing"]) > 0.01:
                    issues.append("   bank %s: Tally %.2f vs Odoo %.2f (journal %s)" % (led["name"], -led["closing"], odoo_j, j.name or "-"))
        if abs(got - round(expected, 2)) > 0.01:
            issues.append("account %s (Tally %s): Tally %.2f vs Odoo %.2f" % (
                ", ".join(rec.mapped("name")), names, expected, got))
    # Odoo balances Tally does not know about (reconciliation/suspense leftovers...).
    lines = env["account.move.line"].search([
        ("company_id", "=", company.id), ("parent_state", "=", "posted"), ("date", "<=", PERIOD_END),
        ("account_id", "not in", covered_accounts.ids),
        ("account_id.account_type", "not in", ("asset_receivable", "liability_payable"))])
    extra = {}
    for l in lines:
        extra[l.account_id.name] = extra.get(l.account_id.name, 0.0) + l.balance
    tally_ob_diff = round(sum(-l["opening"] for l in ledgers), 2)
    for name, bal in extra.items():
        bal = round(bal, 2)
        if name == "Tally Opening Balance Equity" and abs(bal + tally_ob_diff) <= 0.01:
            continue  # counterpart of Tally's "difference in opening balances"
        if abs(bal) > 0.01:
            issues.append("Odoo-only balance on %s: %.2f" % (name, bal))
    # Identity integrity.
    dup = env.cr.execute("""SELECT tally_guid, count(*) FROM tally_mapping WHERE instance_id=%s AND tally_guid IS NOT NULL
                            GROUP BY entity, tally_guid HAVING count(*) > 1""", [inst.id])
    dups = env.cr.fetchall()
    if dups:
        issues.append("duplicate mappings: %s" % dups[:5])
    vouchers = [v for v in tally_vouchers(tco) if v["voucher_type"] in ACCOUNTING_TYPES
                or inst._get_voucher_type_parents().get((v["voucher_type"] or "").lower(), "").title() in ACCOUNTING_TYPES]
    live = [v for v in vouchers if not (v.get("is_cancelled") or v.get("is_optional"))]
    mapped = env["tally.mapping"].search([
        ("instance_id", "=", inst.id), ("tally_guid", "in", [v["guid"] for v in live]),
        ("entity", "in", ("sales", "purchase", "credit_note", "debit_note", "receipt", "payment",
                          "journal", "contra", "stock_journal"))])
    unmapped = [v for v in live if v["guid"] not in set(mapped.mapped("tally_guid"))
                and any(float(e["amount"] or 0) for e in v["ledger_entries"])]
    if unmapped:
        issues.append("%s Tally voucher(s) not linked to Odoo: %s" % (
            len(unmapped), [(v["voucher_type"], v["voucher_number"]) for v in unmapped[:8]]))
    failed_q = env["tally.sync.queue"].search([("instance_id", "=", inst.id), ("state", "=", "failed")])
    if failed_q:
        issues.append("failed queue items: %s" % [(q.entity, (q.error or "")[:120]) for q in failed_q[:6]])
    step = {"step": label, "tally_ledgers": len(ledgers), "tally_vouchers": len(live),
            "party_total_tally": round(partner_total_t, 2), "party_total_odoo": round(partner_total_o, 2),
            "issues": issues}
    REPORT["steps"].append(step)
    log("AUDIT %-45s ledgers=%s vouchers=%s issues=%s" % (label, len(ledgers), len(live), len(issues)))
    for i in issues:
        log("   ! %s" % i)
    if expect_clean and issues:
        REPORT["failures"].append({label: issues})
    return issues


def snapshot(inst):
    Q = env["tally.sync.queue"]
    return {
        "moves": env["account.move"].search_count([("company_id", "=", inst.company_id.id)]),
        "payments": env["account.payment"].search_count([("company_id", "=", inst.company_id.id)]),
        "partners": env["res.partner"].search_count([]),
        "mappings": env["tally.mapping"].search_count([("instance_id", "=", inst.id)]),
        "tally_vouchers": len(tally_vouchers(inst.tally_company)),
        "queue_acked": Q.search_count([("instance_id", "=", inst.id), ("state", "=", "acked")]),
    }


def idempotent(inst, label):
    """A second full cycle must not create or send anything."""
    before = snapshot(inst)
    sync(inst)
    after = snapshot(inst)
    if before != after:
        REPORT["failures"].append({label + " (idempotency)": [before, after]})
        log("   ! NOT IDEMPOTENT %s -> %s" % (before, after))
    else:
        log("IDEMPOTENT %s" % label)


# ----------------------------------------------------------------- setup
def make_instance(company, tally_company, name, sot="bidirectional", history_from=None):
    env["tally.instance"].search([("company_id", "=", company.id)]).write({"active": False})
    inst = env["tally.instance"].create({
        "name": name, "company_id": company.id, "tally_company": tally_company,
        "connection_mode": "direct", "tally_host": TALLY_HOST, "tally_port": 9000,
        "auto_post": True, "direct_auto_pull": False, "tally_educational_mode": True,
        "history_from": history_from or datetime.date(2026, 4, 1), "odoo_role": "full",
        "tally_inventory": "accounts_only",
    })
    inst.action_load_default_entities()
    for cfg in inst.entity_config_ids:
        cfg.write({"enabled": True, "direction": "both", "source_of_truth": sot})
    env.cr.commit()
    return inst


def india(company):
    inr = env["res.currency"].with_context(active_test=False).search([("name", "=", "INR")], limit=1)
    inr.active = True
    vals = {"country_id": env.ref("base.in").id, "state_id": env.ref("base.state_in_mh").id}
    if company.currency_id != inr and not env["account.move.line"].search_count([("company_id", "=", company.id)]):
        vals["currency_id"] = inr.id
    company.write(vals)


def odoo_masters(company, prefix):
    env_c = env(context=dict(env.context, allowed_company_ids=[company.id]))
    Acc = env_c["account.account"]
    cvals = {"company_ids": [(6, 0, company.ids)]} if "company_ids" in Acc._fields else {"company_id": company.id}
    def account(name, code, atype):
        acc = Acc.search([("name", "=", name)] + ([("company_ids", "in", company.ids)] if "company_ids" in Acc._fields else [("company_id", "=", company.id)]), limit=1)
        return acc or Acc.create(dict(cvals, name=name, code=code, account_type=atype))
    sales = account(prefix + " Sales", prefix[-2:] + "4001", "income")
    purchases = account(prefix + " Purchases", prefix[-2:] + "5001", "expense")
    rent = account(prefix + " Rent", prefix[-2:] + "5002", "expense")
    out_cgst = account(prefix + " Output CGST", prefix[-2:] + "2101", "liability_current")
    out_sgst = account(prefix + " Output SGST", prefix[-2:] + "2102", "liability_current")
    in_cgst = account(prefix + " Input CGST", prefix[-2:] + "1301", "asset_current")
    in_sgst = account(prefix + " Input SGST", prefix[-2:] + "1302", "asset_current")
    def tax(name, amount, use, acc):
        t = env_c["account.tax"].search([("name", "=", name), ("company_id", "=", company.id)], limit=1)
        if t:
            return t
        rep = lambda: [(0, 0, {"repartition_type": "base"}), (0, 0, {"repartition_type": "tax", "account_id": acc.id})]
        return env_c["account.tax"].create({"name": name, "amount": amount, "amount_type": "percent",
                                            "type_tax_use": use, "company_id": company.id,
                                            "invoice_repartition_line_ids": rep(), "refund_repartition_line_ids": rep()})
    taxes = {
        "out": tax(prefix + " Output CGST 9%", 9, "sale", out_cgst) | tax(prefix + " Output SGST 9%", 9, "sale", out_sgst),
        "in": tax(prefix + " Input CGST 9%", 9, "purchase", in_cgst) | tax(prefix + " Input SGST 9%", 9, "purchase", in_sgst),
    }
    bank_acc = account(prefix + " Bank", prefix[-2:] + "1101", "asset_cash")
    bank = env_c["account.journal"].search([("company_id", "=", company.id), ("code", "=", prefix[-3:].upper() + "B")], limit=1) or \
        env_c["account.journal"].create({"name": prefix + " Bank", "type": "bank", "code": prefix[-3:].upper() + "B",
                                         "company_id": company.id, "default_account_id": bank_acc.id})
    mh = env.ref("base.state_in_mh")
    cust = env_c["res.partner"].create({"name": prefix + " Customer A", "company_id": company.id, "customer_rank": 1,
                                        "state_id": mh.id, "country_id": env.ref("base.in").id,
                                        "street": "12 MG Road", "city": "Pune", "zip": "411001"})
    vend = env_c["res.partner"].create({"name": prefix + " Vendor B", "company_id": company.id, "supplier_rank": 1,
                                        "state_id": mh.id, "country_id": env.ref("base.in").id})
    return {"sales": sales, "purchases": purchases, "rent": rent, "taxes": taxes, "bank": bank,
            "customer": cust, "vendor": vend, "env": env_c}


def odoo_documents(m, company, date, tag):
    env_c = m["env"]
    inv = env_c["account.move"].create({
        "move_type": "out_invoice", "partner_id": m["customer"].id, "invoice_date": date, "company_id": company.id,
        "invoice_line_ids": [(0, 0, {"name": "Consulting %s" % tag, "quantity": 2, "price_unit": 1000.0,
                                     "account_id": m["sales"].id, "tax_ids": [(6, 0, m["taxes"]["out"].ids)]})]})
    inv.action_post()
    bill = env_c["account.move"].create({
        "move_type": "in_invoice", "partner_id": m["vendor"].id, "invoice_date": date, "company_id": company.id,
        "ref": "VB-%s" % tag,
        "invoice_line_ids": [(0, 0, {"name": "Supplies %s" % tag, "quantity": 1, "price_unit": 500.0,
                                     "account_id": m["purchases"].id, "tax_ids": [(6, 0, m["taxes"]["in"].ids)]})]})
    bill.action_post()
    pay = env_c["account.payment.register"].with_context(active_model="account.move", active_ids=inv.ids).create({
        "journal_id": m["bank"].id, "payment_date": date}).action_create_payments()
    jv = env_c["account.move"].create({
        "move_type": "entry", "date": date, "company_id": company.id, "ref": "JV %s" % tag,
        "line_ids": [(0, 0, {"name": "Rent", "account_id": m["rent"].id, "debit": 300.0}),
                     (0, 0, {"name": "Bank", "account_id": m["bank"].default_account_id.id, "credit": 300.0})]})
    jv.action_post()
    return {"invoice": inv, "bill": bill, "journal": jv}


def tally_side_entries(tco, prefix, customer_ledger, sales_ledger, bank_ledger, expense_ledger):
    """Vouchers typed by a Tally user (no Odoo identity)."""
    msgs = [
        B.build_voucher_xml("Sales", "", D_AUG31, customer_ledger, is_invoice=False, reference="T-%s-S1" % prefix,
                            ledger_entries=[{"ledger": customer_ledger, "amount": -1500.0,
                                             "bill_allocations": [{"type": "New Ref", "name": "T-%s-S1" % prefix, "amount": -1500.0}]},
                                            {"ledger": sales_ledger, "amount": 1500.0}]),
        B.build_voucher_xml("Payment", "", D2, expense_ledger, is_invoice=False, reference="T-%s-P1" % prefix,
                            ledger_entries=[{"ledger": expense_ledger, "amount": -250.0},
                                            {"ledger": bank_ledger, "amount": 250.0}]),
        B.build_voucher_xml("Receipt", "", D_OCT31, customer_ledger, is_invoice=False, reference="T-%s-R1" % prefix,
                            ledger_entries=[{"ledger": customer_ledger, "amount": 700.0,
                                             "bill_allocations": [{"type": "Agst Ref", "name": "T-%s-S1" % prefix, "amount": 700.0}]},
                                            {"ledger": bank_ledger, "amount": -700.0}]),
    ]
    for m in msgs:
        tally_import([m.replace("<VOUCHERNUMBER></VOUCHERNUMBER>", "")], tco)


def find_tally_voucher(tco, reference):
    vs = tally_vouchers(tco, formula='$Reference = %s' % B.tdl_string(reference))
    return vs[0] if vs else None


# ----------------------------------------------------------------- scenarios
def scenario_two_way(tco, prefix):
    """Both greenfield: Odoo and Tally start empty and are used side by side."""
    company = env.company
    india(company)
    inst = make_instance(company, tco, "S1 %s" % tco)
    m = odoo_masters(company, prefix)
    docs = odoo_documents(m, company, D1, prefix)
    env.cr.commit()
    failed = sync(inst)
    audit(inst, "1. Odoo documents pushed")
    idempotent(inst, "1")
    # Tally side entries referencing ledgers that Odoo created.
    tally_side_entries(tco, prefix, m["customer"].name, m["sales"].name, m["bank"].default_account_id.name, m["rent"].name)
    sync(inst)
    audit(inst, "2. Tally vouchers pulled")
    idempotent(inst, "2")
    # Edit in Tally: a Tally-origin sales voucher amount changes.
    v = find_tally_voucher(tco, "T-%s-S1" % prefix)
    alter = B.build_voucher_xml("Sales", v["voucher_number"], D_AUG31, m["customer"].name, is_invoice=False, reference=v["reference"],
                                ledger_entries=[{"ledger": m["customer"].name, "amount": -1800.0,
                                                 "bill_allocations": [{"type": "New Ref", "name": v["reference"], "amount": -1800.0}]},
                                                {"ledger": m["sales"].name, "amount": 1800.0}],
                                alter_address={"voucher_number": v["voucher_number"], "date": D_AUG31, "voucher_type": "Sales"})
    tally_import([alter], tco)
    sync(inst)
    audit(inst, "3. Tally edit of Tally voucher")
    # Edit in Tally of an Odoo-origin journal (accountant corrects rent).
    mp = env["tally.mapping"].search([("instance_id", "=", inst.id), ("odoo_model_name", "=", "account.move"),
                                      ("odoo_res_id", "=", docs["journal"].id)])
    # A Tally user edits the exact voucher on screen; the simulation addresses it
    # the only unambiguous way available for Odoo-created vouchers: REMOTEID.
    alter = B.build_voucher_xml("Journal", mp.tally_voucher_number, D1, "", is_invoice=False,
                                ledger_entries=[{"ledger": m["rent"].name, "amount": -350.0},
                                                {"ledger": m["bank"].default_account_id.name, "amount": 350.0}],
                                guid=mp.remote_id)
    tally_import([alter], tco)
    sync(inst)
    audit(inst, "4. Tally edit of Odoo journal")
    # Edit in Odoo of an Odoo invoice: reset, change quantity, re-post.
    inv = docs["invoice"]
    inv.button_draft()
    inv.invoice_line_ids[0].quantity = 3
    inv.action_post()
    env.cr.commit()
    sync(inst)
    audit(inst, "5. Odoo edit of Odoo invoice")
    # Cancel in Odoo (vendor bill) and in Tally (Tally payment voucher).
    docs["bill"].button_draft()
    docs["bill"].button_cancel()
    env.cr.commit()
    pv = find_tally_voucher(tco, "T-%s-P1" % prefix)
    tally_import([B.build_voucher_cancel_xml("Payment", pv["voucher_number"], D2, "Cancelled in Tally")], tco)
    sync(inst)
    audit(inst, "6. Cancel both sides")
    # Renames both sides.
    m["customer"].name = m["customer"].name + " Pvt Ltd"
    env.cr.commit()
    ren = '''<TALLYMESSAGE xmlns:UDF="TallyUDF"><LEDGER NAME="%s" ACTION="Alter"><NAME.LIST TYPE="String"><NAME>%s</NAME></NAME.LIST></LEDGER></TALLYMESSAGE>''' % (
        B.xml_escape(m["vendor"].name), B.xml_escape(m["vendor"].name + " & Sons"))
    tally_import([ren], tco, report_type="All Masters")
    sync(inst)
    env.invalidate_all()
    if m["vendor"].name != "%s Vendor B & Sons" % prefix:
        REPORT["failures"].append({"7. vendor rename from Tally": m["vendor"].name})
    tl = {l["name"] for l in tally_ledgers(tco)}
    if m["customer"].name not in tl or ("%s Customer A" % prefix) in tl:
        REPORT["failures"].append({"7. customer rename to Tally": sorted(n for n in tl if "Customer" in n)})
    audit(inst, "7. Renames both sides")
    idempotent(inst, "7")
    return inst


def scenario_tally_brownfield(tco):
    """Tally has history, Odoo is new: full onboarding pull, then continue two-way."""
    company = env.company
    india(company)
    inst = make_instance(company, tco, "S2 %s" % tco, sot="bidirectional")
    inst._direct_pull()
    env.cr.commit()
    audit(inst, "1. Onboarding pull of existing Tally books")
    idempotent(inst, "1")
    # Continue: Odoo raises a new invoice to an existing Tally customer.
    partner = env["res.partner"].search([("name", "=", "Bharat Steel & Alloys Pvt Ltd")], limit=1)
    sales = env["tally.mapping"].search([("instance_id", "=", inst.id), ("entity", "=", "account_ledger"),
                                         ("tally_name", "=", "Sales Account")], limit=1)
    account = env["account.account"].browse(sales.odoo_res_id) if sales else env["account.account"].search([("name", "=", "Sales Account")], limit=1)
    inv = env["account.move"].create({
        "move_type": "out_invoice", "partner_id": partner.id, "invoice_date": D1,
        "invoice_line_ids": [(0, 0, {"name": "Odoo side sale", "quantity": 1, "price_unit": 4321.0,
                                     "account_id": account.id, "tax_ids": [(6, 0, [])]})]})
    inv.action_post()
    env.cr.commit()
    sync(inst)
    audit(inst, "2. Odoo invoice to existing Tally party")
    idempotent(inst, "2")
    return inst


def scenario_odoo_brownfield(tco, prefix):
    """Odoo has history, Tally is new: push existing data, then continue two-way."""
    company = env.company
    india(company)
    env["tally.instance"].search([]).write({"active": False})
    env.cr.commit()
    m = odoo_masters(company, prefix)
    docs = odoo_documents(m, company, D1, prefix + "a")
    odoo_documents(m, company, D2, prefix + "b")
    env.cr.commit()
    inst = make_instance(company, tco, "S3 %s" % tco)
    inst.action_push_existing_odoo_data()
    env.cr.commit()
    sync(inst, rounds=5)
    audit(inst, "1. Existing Odoo data pushed to new Tally")
    idempotent(inst, "1")
    tally_side_entries(tco, prefix, m["customer"].name, m["sales"].name, m["bank"].default_account_id.name, m["rent"].name)
    sync(inst)
    audit(inst, "2. Tally entries after Odoo onboarding")
    idempotent(inst, "2")
    return inst


def scenario_multi_company(tco_a, tco_b):
    """Two Odoo companies <-> two Tally companies (both already in use)."""
    company_a = env.company
    india(company_a)
    company_b = env["res.company"].create({"name": "Second Company", "currency_id": company_a.currency_id.id,
                                           "country_id": env.ref("base.in").id,
                                           "state_id": env.ref("base.state_in_mh").id})
    env.user.company_ids |= company_b
    chart = env["account.chart.template"]
    try:
        chart.try_loading("generic_coa", company_b, install_demo=False)
    except Exception as e:
        log("chart for company B: %s" % e)
    env.cr.commit()
    inst_a = make_instance(company_a, tco_a, "S4 A")
    inst_b = make_instance(company_b, tco_b, "S4 B")
    inst_a._direct_pull(); env.cr.commit()
    inst_b._direct_pull(); env.cr.commit()
    audit(inst_a, "1a. Company A pulled from %s" % tco_a)
    audit(inst_b, "1b. Company B pulled from %s" % tco_b)
    shared = env["res.partner"].create({"name": "Group Shared Customer", "customer_rank": 1, "company_id": False})
    own_b = env["res.partner"].create({"name": "Company B Local Customer", "customer_rank": 1, "company_id": company_b.id})
    env.cr.commit()
    sync(inst_a); sync(inst_b)
    names_a = {l["name"] for l in tally_ledgers(tco_a)}
    names_b = {l["name"] for l in tally_ledgers(tco_b)}
    checks = {
        "shared in A": shared.name in names_a, "shared in B": shared.name in names_b,
        "local B not in A": own_b.name not in names_a, "local B in B": own_b.name in names_b,
    }
    log("multi-company placement %s" % checks)
    if not all(checks.values()):
        REPORT["failures"].append({"multi-company placement": checks})
    # Cross-company isolation of identity maps.
    leak = env["tally.mapping"].search_count([("instance_id", "=", inst_a.id), ("company_id", "!=", company_a.id)])
    if leak:
        REPORT["failures"].append({"mapping company leak": leak})
    audit(inst_a, "2a. After shared/local partners (A)")
    audit(inst_b, "2b. After shared/local partners (B)")
    idempotent(inst_a, "A"); idempotent(inst_b, "B")


def agent_setup(tco, prefix):
    company = env.company
    india(company)
    inst = make_instance(company, tco, "AGENT %s" % tco)
    inst.write({"connection_mode": "agent", "agent_token": "agent-e2e-token", "last_pull": False})
    m = odoo_masters(company, prefix)
    odoo_documents(m, company, D1, prefix)
    env.cr.commit()
    log("agent instance %s ready; queue=%s" % (inst.id, env["tally.sync.queue"].search_count([("instance_id", "=", inst.id)])))


def agent_tally_entries(tco, prefix):
    m_c = env["res.partner"].search([("name", "=", prefix + " Customer A")], limit=1)
    tally_side_entries(tco, prefix, m_c.name, prefix + " Sales", prefix + " Bank", prefix + " Rent")
    env["tally.instance"].search([("active", "=", True)]).write({"last_pull": False})
    env.cr.commit()


def agent_audit(label):
    inst = env["tally.instance"].search([("active", "=", True), ("connection_mode", "=", "agent")], limit=1)
    q = env["tally.sync.queue"].search([("instance_id", "=", inst.id)])
    log("queue states %s" % {st: len(q.filtered(lambda i: i.state == st)) for st in set(q.mapped("state"))})
    audit(inst, label)
    env["tally.instance"].search([("active", "=", True)]).write({"last_pull": False})
    env.cr.commit()


# ----------------------------------------------------------------- main
try:
    s = os.environ["SCENARIO"]
    tco = os.environ["TALLY_CO"]
    if s == "s1":
        scenario_two_way(tco, os.environ.get("PREFIX", "S1"))
    elif s == "s2":
        scenario_tally_brownfield(tco)
    elif s == "s3":
        scenario_odoo_brownfield(tco, os.environ.get("PREFIX", "S3"))
    elif s == "s4":
        a, b = tco.split("|")
        scenario_multi_company(a, b)
    elif s == "agent_setup":
        agent_setup(tco, os.environ.get("PREFIX", "AG"))
    elif s == "agent_tally":
        agent_tally_entries(tco, os.environ.get("PREFIX", "AG"))
    elif s.startswith("agent_audit"):
        agent_audit(os.environ.get("LABEL", s))
except Exception:
    REPORT["failures"].append({"exception": traceback.format_exc()})
    log(traceback.format_exc())
finally:
    with open(os.environ["REPORT"], "w") as fh:
        json.dump(REPORT, fh, indent=2, default=str)
    log("RESULT %s failures=%s" % (REPORT["scenario"], len(REPORT["failures"])))
