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


def compute_payload_hash(data):
    """Compute SHA-256 hash of a normalized JSON-serializable structure."""
    serialized = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class SyncEngine:
    def __init__(self, env, instance):
        self.env = env
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

    def process_inbound_batch(self, entity, records, alterid=None):
        """Main entry point for processing a batch of records from Tally."""
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

        for rec in records:
            rec_alterid = int(rec.get("alterid") or 0)
            if rec_alterid > max_alterid:
                max_alterid = rec_alterid

            # Echo-suppression check
            guid = rec.get("guid")
            p_hash = compute_payload_hash(rec)
            mapping = self._get_mapping(entity, guid=guid) if guid else None

            if mapping and mapping.content_hash == p_hash and mapping.last_origin == "odoo":
                # Echo suppressed
                continue

            try:
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
            except Exception as e:
                errors += 1
                _logger.exception("Error upserting %s: %s", entity, e)
                self.env["tally.sync.log"].log(
                    self.instance, "tally_to_odoo", entity, "error",
                    f"Failed upserting {entity} {rec.get('name') or rec.get('voucher_number')}: {str(e)}",
                    detail=str(rec),
                    tally_guid=guid,
                )

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
            # Code prefix generated if needed
            vals["code_prefix_start"] = name[:4].upper()
            rec = Group.create(vals)
        return rec

    def _upsert_account_ledger(self, data):
        """Upsert account.account from Tally General Ledger."""
        name = data.get("name")
        parent = data.get("parent", "")
        if not name:
            return False
        Account = self.env["account.account"]

        # Search existing by name/code
        rec = Account.search([
            ("name", "=", name),
            ("company_id", "=", self.company.id)
        ], limit=1)

        # Map Tally parent group to Odoo account_type
        account_type = self._map_tally_group_to_account_type(parent)

        vals = {
            "name": name,
            "company_id": self.company.id,
            "account_type": account_type,
        }

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

        # Search by GSTIN or Name
        gstin = data.get("gstin")
        domain = [("company_id", "in", (False, self.company.id))]
        if gstin:
            rec = Partner.search(domain + [("vat", "=", gstin)], limit=1)
        else:
            rec = Partner.search(domain + [("name", "=", name)], limit=1)

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
        return rec

    def _upsert_uom(self, data):
        """Upsert uom.uom from Tally <UNIT>."""
        name = data.get("name")
        if not name:
            return False
        Uom = self.env["uom.uom"]
        rec = Uom.search([("name", "=", name)], limit=1)
        if not rec:
            # Get default Unit category
            cat = self.env["uom.category"].search([], limit=1)
            rec = Uom.create({
                "name": name,
                "category_id": cat.id,
                "uom_type": "reference",
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
        rec = Product.search([
            ("name", "=", name),
            ("company_id", "in", (False, self.company.id))
        ], limit=1)

        uom_name = data.get("base_uom", "Units")
        uom = self.env["uom.uom"].search([("name", "=", uom_name)], limit=1)
        if not uom:
            uom = self.env.ref("uom.product_uom_unit", raise_if_not_found=False) or self.env["uom.uom"].search([], limit=1)

        vals = {
            "name": name,
            "detailed_type": "product",
            "uom_id": uom.id if uom else False,
            "uom_po_id": uom.id if uom else False,
            "standard_price": float(data.get("opening_rate") or 0.0),
            "company_id": self.company.id,
        }

        # Check HSN code
        if data.get("hsn_code") and hasattr(Product, "l10n_in_hsn_code"):
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

    def _upsert_invoice_move(self, data, move_type="out_invoice"):
        """Generic handler for customer and vendor invoices/refunds."""
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

        # Prepare invoice lines
        lines = []
        inv_entries = data.get("inventory_entries", [])
        if inv_entries:
            for ie in inv_entries:
                product = self._get_or_create_product(ie.get("item"))
                lines.append((0, 0, {
                    "product_id": product.id if product else False,
                    "name": ie.get("item") or "Item",
                    "quantity": float(ie.get("qty") or 1.0),
                    "price_unit": float(ie.get("rate") or abs(float(ie.get("amount") or 0.0))),
                    "discount": float(ie.get("discount") or 0.0),
                }))
        else:
            # Fallback to ledger entries if pure accounting invoice
            for le in data.get("ledger_entries", []):
                if le.get("ledger") != partner_name:
                    account = self._get_or_create_account(le.get("ledger"))
                    lines.append((0, 0, {
                        "name": le.get("ledger") or "Line",
                        "account_id": account.id if account else False,
                        "quantity": 1,
                        "price_unit": abs(float(le.get("amount") or 0.0)),
                    }))

        # Default Journal
        journal_type = "sale" if move_type in ("out_invoice", "out_refund") else "purchase"
        journal = self.env["account.journal"].search([
            ("type", "=", journal_type),
            ("company_id", "=", self.company.id)
        ], limit=1)

        vals = {
            "move_type": move_type,
            "partner_id": partner.id if partner else False,
            "invoice_date": date_str,
            "date": date_str,
            "ref": data.get("reference") or vch_num,
            "narration": data.get("narration"),
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

        journal = self.env["account.journal"].search([
            ("type", "in", ("bank", "cash")),
            ("company_id", "=", self.company.id)
        ], limit=1)

        vals = {
            "payment_type": pay_type,
            "partner_type": "customer" if is_receipt else "supplier",
            "partner_id": partner.id if partner else False,
            "amount": total_amount,
            "date": date_str,
            "ref": vch_num,
            "journal_id": journal.id if journal else False,
            "company_id": self.company.id,
        }

        rec = Payment.search([
            ("ref", "=", vch_num),
            ("payment_type", "=", pay_type),
            ("company_id", "=", self.company.id)
        ], limit=1)

        if rec:
            rec.write(vals)
        else:
            rec = Payment.create(vals)
        return rec

    def _upsert_journal_voucher(self, data):
        """Upsert account.move (entry) from Tally Journal."""
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

        journal = self.env["account.journal"].search([
            ("type", "=", "general"),
            ("company_id", "=", self.company.id)
        ], limit=1)

        vals = {
            "move_type": "entry",
            "date": date_str,
            "ref": vch_num,
            "narration": data.get("narration"),
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
        rec = Map.search([("tally_group_name", "=", tally_group)], limit=1)
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
        last = Account.search([
            ("code", "=like", f"{prefix}%"),
            ("company_id", "=", self.company.id)
        ], order="code desc", limit=1)
        if last and last.code.isdigit():
            return str(int(last.code) + 1)
        return f"{prefix}001"

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
        return p

    def _get_or_create_product(self, name):
        if not name:
            return False
        Product = self.env["product.product"]
        p = Product.search([("name", "=", name), ("company_id", "in", (False, self.company.id))], limit=1)
        if not p:
            p = Product.create({
                "name": name,
                "detailed_type": "product",
                "company_id": self.company.id,
            })
        return p

    def _get_or_create_account(self, name):
        if not name:
            return False
        Account = self.env["account.account"]
        a = Account.search([("name", "=", name), ("company_id", "=", self.company.id)], limit=1)
        if not a:
            a = Account.create({
                "name": name,
                "code": self._generate_account_code("expense"),
                "account_type": "expense",
                "company_id": self.company.id,
            })
        return a
