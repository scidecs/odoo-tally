# -*- coding: utf-8 -*-
"""Sync Engine Service for TallyPrime <-> Odoo 19.

Handles:
- Orchestrating inbound Tally -> Odoo records (Masters & Vouchers)
- Orchestrating outbound Odoo -> Tally records into tally.sync.queue
- Identity mapping management (tally.mapping)
- Content hashing & echo-suppression
- Source of truth / conflict resolution
- Logging to tally.sync.log
"""
import hashlib
import json
import logging
try:
    from odoo import fields, _
except ImportError:
    # Standalone test environment without Odoo runtime
    class _MockFields:
        @staticmethod
        def now():
            from datetime import datetime
            return datetime.now()
    fields = _MockFields()
    _ = lambda s: s

_logger = logging.getLogger(__name__)


def voucher_type_to_entity(vch_type):
    """Map a Tally voucher type name to our entity code."""
    t = (vch_type or "").lower()
    if "credit note" in t:
        return "credit_note"
    if "debit note" in t:
        return "debit_note"
    if "sale" in t:
        return "sales"
    if "purchase" in t:
        return "purchase"
    if "receipt" in t:
        return "receipt"
    if "payment" in t:
        return "payment"
    if "contra" in t:
        return "contra"
    return "journal"


def compute_payload_hash(data):
    """Compute SHA-256 hash of a normalized JSON-serializable structure."""
    serialized = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class SyncEngine:
    def __init__(self, env, instance):
        self.env = env(context=dict(env.context, tally_sync_origin="tally", tally_no_sync=True), su=True)
        self.instance = instance
        self.company = instance.company_id

    def get_entity_config(self, entity):
        """Get or initialize entity configuration for this instance."""
        Config = self.env["tally.entity.config"]
        cfg = Config.search([
            ("instance_id", "=", self.instance.id),
            ("entity", "=", entity),
        ], limit=1)
        return cfg

    def is_inbound_allowed(self, entity):
        """Check if Tally -> Odoo sync is enabled for this entity."""
        cfg = self.get_entity_config(entity)
        if not cfg or not cfg.enabled:
            return False
        return cfg.direction in ("tally_to_odoo", "both")

    def is_outbound_allowed(self, entity):
        """Check if Odoo -> Tally sync is enabled for this entity."""
        cfg = self.get_entity_config(entity)
        if not cfg or not cfg.enabled:
            return False
        return cfg.direction in ("odoo_to_tally", "both")

    # =========================================================================
    # INBOUND DISPATCHER (Tally -> Odoo)
    # =========================================================================

    VOUCHER_ENTITIES = {
        "sales", "credit_note", "purchase", "debit_note", "receipt",
        "payment", "journal", "contra", "opening_balance", "stock_journal",
    }

    def process_inbound_batch(self, entity, records, alterid=None):
        """Main entry point for processing a batch of records from Tally."""
        if getattr(self.instance, "odoo_role", "full") == "operational" and entity in self.VOUCHER_ENTITIES:
            self.env["tally.sync.log"].log(
                self.instance, "tally_to_odoo", entity, "warning",
                "Odoo is operational-only (Tally keeps the books); inbound voucher import skipped.")
            return {"processed": 0, "skipped": len(records), "status": "operational_skip"}
        if not self.is_inbound_allowed(entity):
            self.env["tally.sync.log"].log(
                self.instance, "tally_to_odoo", entity, "warning",
                f"Sync disabled or not allowed for entity {entity}")
            return {"processed": 0, "skipped": len(records), "status": "disabled"}

        processed = 0
        errors = 0
        max_alterid = 0

        handler_map = {
            "group": self._upsert_group,
            "account_ledger": self._upsert_account_ledger,
            "ledger": self._upsert_party_ledger,
            "uom": self._upsert_uom,
            "stock_group": self._upsert_stock_group,
            "stock_item": self._upsert_stock_item,
            "cost_centre": self._upsert_cost_centre,
            "godown": self._upsert_godown,
            "tax": self._upsert_tax,
            "sales": self._upsert_sales_invoice,
            "credit_note": self._upsert_credit_note,
            "purchase": self._upsert_purchase_bill,
            "debit_note": self._upsert_debit_note,
            "receipt": self._upsert_payment_receipt,
            "payment": self._upsert_payment_receipt,
            "journal": self._upsert_journal_voucher,
            "contra": self._upsert_contra_voucher,
        }

        handler = handler_map.get(entity)
        if not handler:
            _logger.warning("No sync handler for entity: %s", entity)
            return {"processed": 0, "skipped": len(records), "error": f"Unknown entity {entity}"}

        cfg_base = self.get_entity_config(entity)
        base_alterid = cfg_base.last_alterid if cfg_base else 0
        skipped = 0

        for rec in records:
            rec_alterid = int(rec.get("alterid") or 0)
            if rec_alterid > max_alterid:
                max_alterid = rec_alterid
            # Delta skip: Tally AlterID is globally monotonic, so anything at or
            # below the watermark was already synced — cheap to skip before upsert.
            if rec_alterid and base_alterid and rec_alterid <= base_alterid:
                skipped += 1
                continue

            # Echo-suppression check
            guid = rec.get("guid")
            p_hash = compute_payload_hash(rec)
            mapping = self._get_mapping(entity, guid=guid) if guid else None

            if mapping and mapping.content_hash == p_hash and mapping.last_origin == "odoo":
                # Echo suppressed
                continue

            try:
                with self.env.cr.savepoint():
                    odoo_record = handler(rec)
                    if odoo_record:
                        processed += 1
                        self._update_mapping(
                            entity=entity,
                            guid=guid or f"tally_{entity}_{odoo_record.id}",
                            masterid=rec.get("alterid"),
                            model_name=odoo_record._name,
                            res_id=odoo_record.id,
                            content_hash=p_hash,
                            origin="tally",
                        )
                        self._maybe_autopost(entity, odoo_record)
            except Exception as e:
                errors += 1
                _logger.exception("Error upserting %s: %s", entity, e)
                try:
                    self.env["tally.sync.log"].log(
                        self.instance, "tally_to_odoo", entity, "error",
                        f"Failed upserting {entity} {rec.get('name') or rec.get('voucher_number')}: {str(e)}",
                        detail=str(rec),
                        tally_guid=guid,
                    )
                except Exception:
                    pass

        # Advance AlterID watermark
        cfg = self.get_entity_config(entity)
        if cfg and (alterid or max_alterid):
            target_aid = max(int(alterid or 0), max_alterid)
            if target_aid > cfg.last_alterid:
                cfg.write({"last_alterid": target_aid, "last_sync": fields.Datetime.now()})

        self.env["tally.sync.log"].log(
            self.instance, "tally_to_odoo", entity,
            "success" if errors == 0 else "warning",
            f"Processed {processed} record(s), {errors} error(s) for {entity}",
            detail=f"AlterID watermark={cfg.last_alterid if cfg else max_alterid}"
        )

        return {"processed": processed, "errors": errors, "watermark": max_alterid}

    def process_vouchers(self, vouchers, alterid=None):
        """Group a mixed list of parsed vouchers by entity and dispatch each group."""
        groups = {}
        for v in vouchers or []:
            groups.setdefault(voucher_type_to_entity(v.get("voucher_type")), []).append(v)
        results = {}
        for entity, recs in groups.items():
            results[entity] = self.process_inbound_batch(entity, recs, alterid=alterid)
        return results

    def _maybe_autopost(self, entity, record):
        """Post an imported voucher when the instance opts in; leave draft on failure."""
        if not getattr(self.instance, "auto_post", False):
            return
        if entity not in self.VOUCHER_ENTITIES:
            return
        if record._name not in ("account.move", "account.payment"):
            return
        if getattr(record, "state", "") != "draft":
            return
        try:
            with self.env.cr.savepoint():
                record.action_post()
        except Exception as e:
            _logger.info("Auto-post skipped for %s %s: %s", record._name, record.id, e)

    # =========================================================================
    # MASTER UPSERT HANDLERS
    # =========================================================================

    def _upsert_group(self, data):
        """Upsert account.group from Tally <GROUP>."""
        name = data.get("name")
        if not name:
            return False
        Group = self.env["account.group"]
        rec = Group.search([
            ("name", "=", name),
            ("company_id", "=", self.company.id)
        ], limit=1)

        # Parent group lookup
        parent_name = data.get("parent")
        parent_id = False
        if parent_name and parent_name != "Primary":
            parent = Group.search([
                ("name", "=", parent_name),
                ("company_id", "=", self.company.id)
            ], limit=1)
            parent_id = parent.id if parent else False

        vals = {
            "name": name,
            "company_id": self.company.id,
            "parent_id": parent_id,
        }
        if rec:
            rec.write(vals)
        else:
            rec = Group.create(vals)
        return rec

    def _upsert_account_ledger(self, data):
        """Upsert account.account from Tally General Ledger."""
        name = data.get("name")
        parent = data.get("parent", "")
        if not name:
            return False
        Account = self.env["account.account"]

        # 1. Search existing by mapping GUID
        rec = False
        mapping = self._get_mapping("account_ledger", guid=data.get("guid"))
        if mapping and mapping.odoo_res_id:
            rec = Account.browse(mapping.odoo_res_id).exists()

        # 2. Search existing by name/code scoped to company
        if not rec:
            domain = [("name", "=ilike", name)] + self._account_company_domain()
            rec = Account.search(domain, limit=1)

        # Map Tally parent group to Odoo account_type
        account_type = self._map_tally_group_to_account_type(parent)

        vals = {
            "name": name,
            "account_type": account_type,
        }
        vals.update(self._account_company_vals())

        if rec:
            rec.write(vals)
        else:
            # Generate code if new
            code = self._generate_account_code(account_type)
            vals["code"] = code
            rec = Account.create(vals)
        return rec

    def _upsert_party_ledger(self, data):
        """Upsert res.partner from Tally Party Ledger (Debtors/Creditors)."""
        name = data.get("name")
        if not name:
            return False
        Partner = self.env["res.partner"]

        # 1. Search existing by mapping GUID
        rec = False
        mapping = self._get_mapping("ledger", guid=data.get("guid"))
        if mapping and mapping.odoo_res_id:
            rec = Partner.browse(mapping.odoo_res_id).exists()

        # 2. Search by GSTIN (VAT) or Name
        gstin = data.get("gstin")
        domain = [("company_id", "in", (False, self.company.id))]
        if not rec and gstin:
            rec = Partner.search(domain + [("vat", "=", gstin)], limit=1)
        if not rec:
            rec = Partner.search(domain + [("name", "=ilike", name)], limit=1)

        parent = data.get("parent", "")
        is_customer = "debtor" in parent.lower() or "customer" in parent.lower()
        is_supplier = "creditor" in parent.lower() or "vendor" in parent.lower() or "supplier" in parent.lower()

        # State lookup
        state_id = False
        if data.get("state"):
            state = self.env["res.country.state"].search([
                ("name", "ilike", data["state"]),
                ("country_id.code", "=", "IN")
            ], limit=1)
            state_id = state.id if state else False

        country_id = self.env["res.country"].search([("code", "=", "IN")], limit=1).id

        street = ""
        street2 = ""
        addresses = data.get("addresses", [])
        if len(addresses) > 0:
            street = addresses[0]
        if len(addresses) > 1:
            street2 = ", ".join(addresses[1:])

        vals = {
            "name": name,
            "vat": gstin or False,
            "street": street or False,
            "street2": street2 or False,
            "state_id": state_id,
            "country_id": country_id,
            "zip": data.get("pincode") or False,
            "email": data.get("email") or False,
            "phone": data.get("phone") or False,
            "company_id": self.company.id,
            "customer_rank": 1 if is_customer else 0,
            "supplier_rank": 1 if is_supplier else 0,
        }

        if rec:
            rec.write(vals)
        else:
            rec = Partner.create(vals)
        self._ensure_partner_accounts(rec)
        return rec

    def _upsert_uom(self, data):
        """Upsert uom.uom from Tally <UNIT>."""
        name = data.get("name")
        if not name:
            return False
        Uom = self.env["uom.uom"]
        rec = Uom.search([("name", "=ilike", name)], limit=1)
        if not rec:
            rec = Uom.create({
                "name": name,
                "rounding": 1.0 / (10 ** int(data.get("decimal_places") or 0)),
            })
        return rec

    def _upsert_stock_group(self, data):
        """Upsert product.category from Tally <STOCKGROUP>."""
        name = data.get("name")
        if not name:
            return False
        Category = self.env["product.category"]
        rec = Category.search([("name", "=", name)], limit=1)
        if not rec:
            parent_id = False
            if data.get("parent") and data["parent"] != "Primary":
                p = Category.search([("name", "=", data["parent"])], limit=1)
                parent_id = p.id if p else False
            rec = Category.create({"name": name, "parent_id": parent_id})
        return rec

    def _upsert_stock_item(self, data):
        """Upsert product.product from Tally <STOCKITEM>."""
        name = data.get("name")
        if not name:
            return False
        Product = self.env["product.product"]

        # 1. Search existing by mapping GUID
        rec = False
        mapping = self._get_mapping("stock_item", guid=data.get("guid"))
        if mapping and mapping.odoo_res_id:
            rec = Product.browse(mapping.odoo_res_id).exists()

        # 2. Search existing by name scoped to company
        if not rec:
            rec = Product.search([
                ("name", "=ilike", name),
                ("company_id", "in", (False, self.company.id))
            ], limit=1)

        uom_name = data.get("base_uom", "Units")
        uom = self.env["uom.uom"].search([("name", "=", uom_name)], limit=1)
        if not uom:
            uom = self.env.ref("uom.product_uom_unit", raise_if_not_found=False) or self.env["uom.uom"].search([], limit=1)

        vals = {
            "name": name,
            "type": "consu",
            "uom_id": uom.id if uom else False,
            "standard_price": float(data.get("opening_rate") or 0.0),
            "company_id": self.company.id,
        }

        if "is_storable" in Product._fields:
            vals["is_storable"] = True
        # Check HSN code
        if data.get("hsn_code") and "l10n_in_hsn_code" in Product._fields:
            vals["l10n_in_hsn_code"] = data["hsn_code"]

        if rec:
            rec.write(vals)
        else:
            rec = Product.create(vals)
        return rec

    def _upsert_cost_centre(self, data):
        """Upsert account.analytic.account from Tally <COSTCENTRE>."""
        name = data.get("name")
        if not name:
            return False
        Analytic = self.env["account.analytic.account"]
        rec = Analytic.search([
            ("name", "=", name),
            ("company_id", "in", (False, self.company.id))
        ], limit=1)

        # Plan / Category
        plan = self.env["account.analytic.plan"].search([("company_id", "in", (False, self.company.id))], limit=1)
        if not plan:
            plan = self.env["account.analytic.plan"].create({"name": "Default Plan", "company_id": self.company.id})

        vals = {
            "name": name,
            "plan_id": plan.id,
            "company_id": self.company.id,
        }
        if rec:
            rec.write(vals)
        else:
            rec = Analytic.create(vals)
        return rec

    def _upsert_godown(self, data):
        """Upsert stock.location from Tally <GODOWN>."""
        name = data.get("name")
        if not name or name == "Main Location":
            return False
        Location = self.env["stock.location"]
        rec = Location.search([
            ("name", "=", name),
            ("company_id", "in", (False, self.company.id))
        ], limit=1)
        if not rec:
            parent_loc = self.env.ref("stock.stock_location_stock", raise_if_not_found=False) or Location.search([("usage", "=", "internal")], limit=1)
            rec = Location.create({
                "name": name,
                "location_id": parent_loc.id if parent_loc else False,
                "usage": "internal",
                "company_id": self.company.id,
            })
        return rec

    def _upsert_tax(self, data):
        """Upsert account.tax from Tally Tax Ledger."""
        name = data.get("name")
        rate = float(data.get("rate_of_tax") or 0.0)
        if not name:
            return False
        Tax = self.env["account.tax"]
        rec = Tax.search([
            ("name", "=", name),
            ("company_id", "=", self.company.id)
        ], limit=1)
        vals = {
            "name": name,
            "amount": rate,
            "amount_type": "percent",
            "type_tax_use": "sale",
            "company_id": self.company.id,
        }
        if rec:
            rec.write(vals)
        else:
            rec = Tax.create(vals)
        return rec

    # =========================================================================
    # VOUCHER UPSERT HANDLERS
    # =========================================================================

    def _upsert_sales_invoice(self, data):
        """Upsert account.move (out_invoice) from Tally Sales Voucher."""
        return self._upsert_invoice_move(data, move_type="out_invoice")

    def _upsert_purchase_bill(self, data):
        """Upsert account.move (in_invoice) from Tally Purchase Voucher."""
        return self._upsert_invoice_move(data, move_type="in_invoice")

    def _upsert_credit_note(self, data):
        """Upsert account.move (out_refund) from Tally Credit Note."""
        return self._upsert_invoice_move(data, move_type="out_refund")

    def _upsert_debit_note(self, data):
        """Upsert account.move (in_refund) from Tally Debit Note."""
        return self._upsert_invoice_move(data, move_type="in_refund")

    def _find_or_create_tax(self, tax_name, rate=0.0, tax_type="sale"):
        """Find or create matching account.tax in Odoo."""
        Tax = self.env["account.tax"]
        tax = Tax.search([
            ("name", "=ilike", tax_name),
            ("type_tax_use", "=", tax_type),
            ("company_id", "=", self.company.id),
        ], limit=1)
        if not tax:
            import re
            m = re.search(r"(\d+(?:\.\d+)?)\s*%", tax_name)
            calc_rate = float(m.group(1)) if m else rate
            if calc_rate > 0:
                tax = Tax.search([
                    ("amount", "=", calc_rate),
                    ("amount_type", "=", "percent"),
                    ("type_tax_use", "=", tax_type),
                    ("company_id", "=", self.company.id),
                ], limit=1)
            if not tax:
                tax = Tax.create({
                    "name": tax_name,
                    "amount": calc_rate,
                    "amount_type": "percent",
                    "type_tax_use": tax_type,
                    "company_id": self.company.id,
                })
        return tax

    def _upsert_invoice_move(self, data, move_type="out_invoice"):
        """Generic handler for customer and vendor invoices/refunds with GST tax mapping."""
        Move = self.env["account.move"]
        vch_num = data.get("voucher_number")
        date_str = data.get("date")

        # Find partner
        partner_name = data.get("party_ledger")
        partner = self._get_or_create_partner(partner_name, is_supplier=(move_type in ("in_invoice", "in_refund")))

        # Check existing move by mapping or ref
        mapping = self._get_mapping("sales" if move_type == "out_invoice" else "purchase", guid=data.get("guid"))
        if mapping and mapping.odoo_res_id:
            move = Move.browse(mapping.odoo_res_id).exists()
        else:
            move = Move.search([
                ("name", "=", vch_num),
                ("move_type", "=", move_type),
                ("company_id", "=", self.company.id)
            ], limit=1)

        # Determine default line account
        default_acc_type = "income" if move_type in ("out_invoice", "out_refund") else "expense"
        default_acc_name = "Sales Account" if default_acc_type == "income" else "Purchase Account"
        default_account = self._get_or_create_account(default_acc_name, default_type=default_acc_type)

        tax_type = "sale" if move_type in ("out_invoice", "out_refund") else "purchase"

        # 1. Detect GST / Tax ledgers from ledger_entries
        tax_ids = []
        extra_charge_lines = []
        for le in data.get("ledger_entries", []):
            led = le.get("ledger", "")
            amt = abs(float(le.get("amount") or 0.0))
            if led == partner_name:
                continue
            led_lower = led.lower()
            if any(k in led_lower for k in ("cgst", "sgst", "igst", "gst", "tax", "vat", "duties")):
                tax_rec = self._find_or_create_tax(led, tax_type=tax_type)
                if tax_rec and tax_rec.id not in tax_ids:
                    tax_ids.append(tax_rec.id)
            elif amt > 0:
                # Supplementary charges / discounts / roundoff
                charge_acc = self._get_or_create_account(led, default_type=default_acc_type)
                extra_charge_lines.append((0, 0, {
                    "name": led,
                    "account_id": charge_acc.id if charge_acc else default_account.id,
                    "quantity": 1,
                    "price_unit": amt if float(le.get("amount") or 0.0) < 0 else -amt,
                }))

        # 2. Prepare invoice lines
        lines = []
        inv_entries = data.get("inventory_entries", [])
        if inv_entries:
            for ie in inv_entries:
                product = self._get_or_create_product(ie.get("item"))
                line_vals = {
                    "product_id": product.id if product else False,
                    "account_id": default_account.id if default_account else False,
                    "name": ie.get("item") or "Item",
                    "quantity": float(ie.get("qty") or 1.0),
                    "price_unit": float(ie.get("rate") or abs(float(ie.get("amount") or 0.0))),
                    "discount": float(ie.get("discount") or 0.0),
                }
                if tax_ids:
                    line_vals["tax_ids"] = [(6, 0, tax_ids)]
                lines.append((0, 0, line_vals))
        else:
            # Fallback to ledger entries if pure accounting invoice
            for le in data.get("ledger_entries", []):
                led = le.get("ledger", "")
                if led != partner_name and not any(k in led.lower() for k in ("cgst", "sgst", "igst", "gst", "tax", "vat", "duties")):
                    account = self._get_or_create_account(led, default_type=default_acc_type)
                    line_vals = {
                        "name": led or "Line",
                        "account_id": account.id if account else (default_account.id if default_account else False),
                        "quantity": 1,
                        "price_unit": abs(float(le.get("amount") or 0.0)),
                    }
                    if tax_ids:
                        line_vals["tax_ids"] = [(6, 0, tax_ids)]
                    lines.append((0, 0, line_vals))

        # Add any extra non-tax ledger charge lines
        lines.extend(extra_charge_lines)

        # Default Journal
        journal_type = "sale" if move_type in ("out_invoice", "out_refund") else "purchase"
        journal = self._get_or_create_journal(journal_type)

        vals = {
            "move_type": move_type,
            "partner_id": partner.id if partner else False,
            "invoice_date": date_str,
            "date": date_str,
            "ref": data.get("reference") or vch_num,
            "narration": f"<p>{data['narration']}</p>" if data.get("narration") else False,
            "company_id": self.company.id,
            "journal_id": journal.id if journal else False,
        }

        if move:
            if move.state == "draft":
                move.invoice_line_ids.unlink()
                vals["invoice_line_ids"] = lines
                move.write(vals)
        else:
            vals["invoice_line_ids"] = lines
            move = Move.create(vals)

        return move

    def _upsert_payment_receipt(self, data):
        """Upsert account.payment from Tally Receipt or Payment Voucher."""
        Payment = self.env["account.payment"]
        vch_type = data.get("voucher_type", "").lower()
        is_receipt = "receipt" in vch_type
        pay_type = "inbound" if is_receipt else "outbound"
        vch_num = data.get("voucher_number")
        date_str = data.get("date")

        partner_name = data.get("party_ledger")
        partner = self._get_or_create_partner(partner_name, is_supplier=not is_receipt)

        # Compute total amount from ledger entries
        total_amount = 0.0
        for le in data.get("ledger_entries", []):
            amt = abs(float(le.get("amount") or 0.0))
            if amt > total_amount:
                total_amount = amt

        journal = self._get_or_create_journal("bank")

        vals = {
            "payment_type": pay_type,
            "partner_type": "customer" if is_receipt else "supplier",
            "partner_id": partner.id if partner else False,
            "amount": total_amount,
            "date": date_str,
            "memo": vch_num,
            "journal_id": journal.id if journal else False,
            "company_id": self.company.id,
        }

        rec = Payment.search([
            ("memo", "=", vch_num),
            ("payment_type", "=", pay_type),
            ("company_id", "=", self.company.id)
        ], limit=1)

        if rec:
            rec.write(vals)
        else:
            rec = Payment.create(vals)
        return rec

    def _upsert_journal_voucher(self, data):
        """Upsert account.move (entry) from Tally Journal with automatic balance check."""
        Move = self.env["account.move"]
        vch_num = data.get("voucher_number")
        date_str = data.get("date")

        lines = []
        for le in data.get("ledger_entries", []):
            amt = float(le.get("amount") or 0.0)
            account = self._get_or_create_account(le.get("ledger"))
            debit = abs(amt) if amt < 0 else 0.0  # Tally credit is negative / positive depending on context
            credit = abs(amt) if amt > 0 else 0.0
            lines.append((0, 0, {
                "name": le.get("ledger") or "Journal Entry",
                "account_id": account.id if account else False,
                "debit": debit,
                "credit": credit,
            }))

        # Automatic balancing check & suspense adjustment
        total_debit = sum(line[2]["debit"] for line in lines)
        total_credit = sum(line[2]["credit"] for line in lines)
        diff = round(total_debit - total_credit, 2)
        if diff != 0:
            rounding_account = self._get_or_create_account("Rounding & Suspense Difference", default_type="expense")
            if diff < 0:
                lines.append((0, 0, {
                    "name": "Rounding / Balance Adjustment",
                    "account_id": rounding_account.id,
                    "debit": abs(diff),
                    "credit": 0.0,
                }))
            else:
                lines.append((0, 0, {
                    "name": "Rounding / Balance Adjustment",
                    "account_id": rounding_account.id,
                    "debit": 0.0,
                    "credit": abs(diff),
                }))

        journal = self._get_or_create_journal("general")

        vals = {
            "move_type": "entry",
            "date": date_str,
            "ref": vch_num,
            "narration": f"<p>{data['narration']}</p>" if data.get("narration") else False,
            "journal_id": journal.id if journal else False,
            "company_id": self.company.id,
            "line_ids": lines,
        }

        rec = Move.search([
            ("ref", "=", vch_num),
            ("move_type", "=", "entry"),
            ("company_id", "=", self.company.id)
        ], limit=1)

        if rec:
            if rec.state == "draft":
                rec.line_ids.unlink()
                rec.write(vals)
        else:
            rec = Move.create(vals)
        return rec

    def _upsert_contra_voucher(self, data):
        """Upsert account.move (contra entry) between Cash and Bank."""
        return self._upsert_journal_voucher(data)

    # =========================================================================
    # HELPER LOOKUPS
    # =========================================================================

    def _get_mapping(self, entity, guid):
        return self.env["tally.mapping"].search([
            ("instance_id", "=", self.instance.id),
            ("entity", "=", entity),
            ("tally_guid", "=", guid),
        ], limit=1)

    def _update_mapping(self, entity, guid, masterid, model_name, res_id, content_hash, origin):
        Mapping = self.env["tally.mapping"]
        rec = self._get_mapping(entity, guid)
        vals = {
            "instance_id": self.instance.id,
            "entity": entity,
            "tally_guid": guid,
            "tally_masterid": str(masterid or ""),
            "odoo_model_name": model_name,
            "odoo_res_id": res_id,
            "content_hash": content_hash,
            "last_origin": origin,
            "last_sync": fields.Datetime.now(),
            "state": "active",
        }
        if rec:
            rec.write(vals)
        else:
            rec = Mapping.create(vals)
        return rec

    def _map_tally_group_to_account_type(self, tally_group):
        """Find the mapped account_type from tally.account.type.map."""
        Map = self.env["tally.account.type.map"]
        rec = Map.search([("tally_group", "=ilike", tally_group)], limit=1)
        if rec:
            return rec.account_type
        # Fallbacks
        grp = (tally_group or "").lower()
        if "bank" in grp or "cash" in grp:
            return "asset_cash"
        if "debtor" in grp:
            return "asset_receivable"
        if "creditor" in grp:
            return "liability_payable"
        if "income" in grp or "sales" in grp:
            return "income"
        if "expense" in grp or "purchase" in grp:
            return "expense"
        if "asset" in grp:
            return "asset_current"
        if "liabilit" in grp:
            return "liability_current"
        return "expense"

    def _account_company_domain(self):
        Account = self.env["account.account"]
        if "company_ids" in Account._fields:
            return [("company_ids", "in", [self.company.id])]
        elif "company_id" in Account._fields:
            return [("company_id", "in", (False, self.company.id))]
        return []

    def _account_company_vals(self):
        Account = self.env["account.account"]
        vals = {}
        if "company_ids" in Account._fields:
            vals["company_ids"] = [(4, self.company.id)]
        elif "company_id" in Account._fields:
            vals["company_id"] = self.company.id
        return vals

    def _generate_account_code(self, account_type):
        """Generate next available account code based on type."""
        prefix_map = {
            "asset_receivable": "100",
            "asset_cash": "101",
            "asset_current": "102",
            "liability_payable": "200",
            "liability_current": "201",
            "equity": "300",
            "income": "400",
            "expense": "500",
        }
        prefix = prefix_map.get(account_type, "900")
        Account = self.env["account.account"]
        domain = [("code", "=like", f"{prefix}%")] + self._account_company_domain()
        last = Account.search(domain, order="code desc", limit=1)
        if last and last.code.isdigit():
            return str(int(last.code) + 1)
        return f"{prefix}001"

    def _ensure_partner_accounts(self, partner):
        """Ensure partner has receivable and payable accounts set for invoice balance lines."""
        Partner = self.env["res.partner"]
        vals = {}
        if "property_account_receivable_id" in Partner._fields and not partner.property_account_receivable_id:
            rec_acc = self._get_or_create_account("Sundry Debtors", default_type="asset_receivable")
            vals["property_account_receivable_id"] = rec_acc.id
        if "property_account_payable_id" in Partner._fields and not partner.property_account_payable_id:
            pay_acc = self._get_or_create_account("Sundry Creditors", default_type="liability_payable")
            vals["property_account_payable_id"] = pay_acc.id
        if vals:
            partner.write(vals)

    def _get_or_create_partner(self, name, is_supplier=False):
        if not name:
            return False
        Partner = self.env["res.partner"]
        p = Partner.search([("name", "=", name), ("company_id", "in", (False, self.company.id))], limit=1)
        if not p:
            p = Partner.create({
                "name": name,
                "company_id": self.company.id,
                "customer_rank": 0 if is_supplier else 1,
                "supplier_rank": 1 if is_supplier else 0,
            })
        self._ensure_partner_accounts(p)
        return p

    def _get_or_create_product(self, name):
        if not name:
            return False
        Product = self.env["product.product"]
        p = Product.search([("name", "=", name), ("company_id", "in", (False, self.company.id))], limit=1)
        if not p:
            p = Product.create({
                "name": name,
                "type": "consu",
                "company_id": self.company.id,
            })
        return p

    def _get_or_create_account(self, name, default_type="expense"):
        if not name:
            return False
        Account = self.env["account.account"]
        domain = [("name", "=", name)] + self._account_company_domain()
        a = Account.search(domain, limit=1)
        if not a:
            vals = {
                "name": name,
                "code": self._generate_account_code(default_type),
                "account_type": default_type,
            }
            vals.update(self._account_company_vals())
            a = Account.create(vals)
        return a

    def _get_or_create_journal(self, journal_type):
        Journal = self.env["account.journal"]
        j = Journal.search([
            ("type", "=", journal_type),
            ("company_id", "=", self.company.id)
        ], limit=1)
        if not j:
            name_map = {
                "sale": ("Customer Invoices", "INV"),
                "purchase": ("Vendor Bills", "BILL"),
                "general": ("Miscellaneous Operations", "MISC"),
                "bank": ("Bank", "BNK"),
                "cash": ("Cash", "CSH"),
            }
            name, code = name_map.get(journal_type, ("General Journal", "GEN"))
            # ensure code is unique
            cnt = Journal.search_count([("code", "=", code), ("company_id", "=", self.company.id)])
            if cnt:
                code = f"{code}{cnt+1}"
            j = Journal.create({
                "name": name,
                "type": journal_type,
                "code": code,
                "company_id": self.company.id,
            })
        return j
