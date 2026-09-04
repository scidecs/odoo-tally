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
            "currency": self._upsert_currency,
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
                        if getattr(self.instance, "verbose_logging", True):
                            nm = (rec.get("name") or rec.get("voucher_number")
                                  or odoo_record.display_name)
                            self.env["tally.sync.log"].log(
                                self.instance, "tally_to_odoo", entity, "success",
                                _("Imported %s") % nm, record_name=nm,
                                odoo_model_name=odoo_record._name, odoo_res_id=odoo_record.id,
                                tally_guid=guid, record_count=1)
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

        # In verbose mode each record is logged individually; only emit a batch
        # summary when verbose logging is off (keeps movement counts un-doubled).
        if not getattr(self.instance, "verbose_logging", True):
            self.env["tally.sync.log"].log(
                self.instance, "tally_to_odoo", entity,
                "success" if errors == 0 else "warning",
                f"Processed {processed} record(s), {errors} error(s) for {entity}",
                detail=f"AlterID watermark={cfg.last_alterid if cfg else max_alterid}",
                record_count=processed,
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

    def _upsert_currency(self, data):
        """Upsert res.currency from Tally <CURRENCY>."""
        name = data.get("name") or ""
        formal = data.get("formal_name") or ""
        symbol = data.get("symbol") or ""
        if not name and not formal and not symbol:
            return False

        Currency = self.env["res.currency"].with_context(active_test=False)
        rec = False

        KNOWN_SYMBOLS = {
            "INR": "₹", "USD": "$", "EUR": "€", "GBP": "£",
            "AED": "AED", "SAR": "SAR", "JPY": "¥", "CAD": "CA$",
            "AUD": "AU$", "SGD": "S$",
        }

        # Determine ISO code
        cur_iso = (formal if len(formal) == 3 else (name if len(name) == 3 else "")).upper()
        if not cur_iso and (name in ("?", "Rs.", "Rs", "₹") or symbol in ("?", "Rs.", "Rs", "₹") or "inr" in formal.lower() or "rupee" in formal.lower()):
            cur_iso = "INR"

        # 1. Search existing by mapping GUID
        mapping = self._get_mapping("currency", guid=data.get("guid"))
        if mapping and mapping.odoo_res_id:
            rec = Currency.browse(mapping.odoo_res_id).exists()

        # 2. Search by ISO code (e.g. INR, USD)
        if not rec and cur_iso:
            rec = Currency.search([("name", "=ilike", cur_iso)], limit=1)

        if not rec and formal and len(formal) <= 5:
            rec = Currency.search([("name", "=ilike", formal)], limit=1)
        if not rec and symbol and symbol not in ("?", "\ufffd"):
            rec = Currency.search([("symbol", "=", symbol)], limit=1)

        dec_places = int(data.get("decimal_places") or 2)
        rounding = 1.0 / (10 ** dec_places)

        if cur_iso == "INR" or symbol in ("?", "Rs.", "Rs", "₹") or name in ("?", "Rs.", "Rs", "₹"):
            cur_symbol = "₹"
            if not cur_iso:
                cur_iso = "INR"
        else:
            cur_symbol = symbol or KNOWN_SYMBOLS.get(cur_iso) or (formal[:3] if formal else cur_iso)
            if cur_symbol in ("?", "\ufffd", ""):
                cur_symbol = KNOWN_SYMBOLS.get(cur_iso, cur_iso or "₹")

        vals = {
            "active": True,
            "rounding": rounding,
            "decimal_places": dec_places,
        }
        if cur_symbol and cur_symbol not in ("?", "\ufffd"):
            vals["symbol"] = cur_symbol

        if rec:
            rec.write(vals)
        else:
            vals["name"] = cur_iso or (formal if len(formal) == 3 else name[:3].upper())
            vals["currency_unit_label"] = formal or name or "Rupees"
            vals["currency_subunit_label"] = data.get("decimal_symbol") or "Paise"
            rec = Currency.create(vals)

        return rec

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
        """Upsert res.partner from Tally Party Ledger (Debtors/Creditors) with full Indian localization."""
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
        gstin = (data.get("gstin") or "").strip()
        domain = [("company_id", "in", (False, self.company.id))]
        if not rec and gstin:
            rec = Partner.search(domain + ["|", ("vat", "=", gstin), ("vat", "=ilike", gstin)], limit=1)
        if not rec:
            rec = Partner.search(domain + [("name", "=ilike", name)], limit=1)

        parent = data.get("parent", "")
        is_customer = "debtor" in parent.lower() or "customer" in parent.lower()
        is_supplier = "creditor" in parent.lower() or "vendor" in parent.lower() or "supplier" in parent.lower()

        # Extract PAN (from field or chars 3-12 of 15-char GSTIN)
        pan = (data.get("pan") or "").strip()
        if not pan and gstin and len(gstin) == 15:
            pan = gstin[2:12].upper()

        # State lookup by name, code or GSTIN state code (first 2 digits)
        state_id = False
        st_name = (data.get("state") or "").strip()
        if not st_name and gstin and len(gstin) >= 2 and gstin[:2].isdigit():
            gst_code = gstin[:2]
            if "l10n_in_tin" in self.env["res.country.state"]._fields:
                st = self.env["res.country.state"].search([
                    ("l10n_in_tin", "=", gst_code),
                    ("country_id.code", "=", "IN")
                ], limit=1)
                if st:
                    state_id = st.id
        if not state_id and st_name:
            import re
            clean_st = re.sub(r"^\d+\s*[-:]\s*", "", st_name).strip()
            st = self.env["res.country.state"].search([
                ("country_id.code", "=", "IN"),
                "|", ("name", "=ilike", clean_st), ("code", "=ilike", clean_st)
            ], limit=1)
            if not st:
                st = self.env["res.country.state"].search([
                    ("country_id.code", "=", "IN"),
                    ("name", "ilike", clean_st)
                ], limit=1)
            state_id = st.id if st else False

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

        # Indian Localization fields (l10n_in)
        if "l10n_in_gstin" in Partner._fields and gstin:
            vals["l10n_in_gstin"] = gstin
        if "l10n_in_pan" in Partner._fields and pan:
            vals["l10n_in_pan"] = pan
        if "l10n_in_gst_treatment" in Partner._fields:
            gst_reg = (data.get("gst_registration_type") or "").lower().strip()
            treat_map = {
                "regular": "regular",
                "composition": "composition",
                "unregistered": "unregistered",
                "consumer": "consumer",
                "overseas": "overseas",
                "special economic zone": "special_economic_zone",
                "sez": "special_economic_zone",
                "deemed export": "deemed_export",
            }
            treatment = treat_map.get(gst_reg)
            if not treatment and gstin:
                treatment = "regular"
            elif not treatment:
                treatment = "unregistered"
            vals["l10n_in_gst_treatment"] = treatment

        if rec:
            if rec.is_company and (rec == self.company.partner_id or rec in self.env["res.company"].sudo().search([]).mapped("partner_id")):
                vals.pop("company_id", None)
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

        rate = float(data.get("rate") or data.get("opening_rate") or data.get("closing_rate") or 0.0)

        vals = {
            "name": name,
            "type": "consu",
            "uom_id": uom.id if uom else False,
            "company_id": self.company.id,
        }
        if rate > 0:
            vals["standard_price"] = rate

        if "is_storable" in Product._fields:
            vals["is_storable"] = True
        # Check HSN code
        if data.get("hsn_code") and "l10n_in_hsn_code" in Product._fields:
            vals["l10n_in_hsn_code"] = data["hsn_code"]

        if rec:
            rec.write(vals)
        else:
            rec = Product.create(vals)

        # Apply stock on-hand quantity matching Tally closing/opening balance
        target_qty = float(data.get("quantity") or data.get("closing_balance") or data.get("opening_balance") or 0.0)
        self._apply_stock_quantities(rec, target_qty, data.get("batch_allocations"))

        return rec

    def _apply_stock_quantities(self, product, target_qty, batch_allocations=None):
        """Apply physical on-hand stock quantities to Odoo stock.quant."""
        if not product or not hasattr(product, "qty_available"):
            return

        Quant = self.env["stock.quant"]
        Location = self.env["stock.location"]
        Warehouse = self.env["stock.warehouse"]

        wh = Warehouse.search([("company_id", "=", self.company.id)], limit=1)
        default_loc = wh.lot_stock_id if wh and wh.lot_stock_id else Location.search([
            ("usage", "=", "internal"),
            ("company_id", "in", (False, self.company.id))
        ], limit=1)

        if not default_loc:
            return

        allocations = batch_allocations or []
        if allocations:
            for alloc in allocations:
                g_name = alloc.get("godown") or "Main Location"
                qty = float(alloc.get("qty") or 0.0)
                if not qty:
                    continue

                target_loc = default_loc
                if g_name and g_name != "Main Location":
                    g_loc = Location.search([
                        ("name", "=ilike", g_name),
                        ("usage", "=", "internal"),
                        ("company_id", "in", (False, self.company.id))
                    ], limit=1)
                    if not g_loc:
                        g_loc = Location.create({
                            "name": g_name,
                            "location_id": default_loc.id,
                            "usage": "internal",
                            "company_id": self.company.id,
                        })
                    target_loc = g_loc

                self._set_location_quant(product, target_loc, qty)
        else:
            if target_qty != 0.0:
                self._set_location_quant(product, default_loc, target_qty)

    def _set_location_quant(self, product, location, qty):
        """Set or adjust stock.quant at a specific internal location."""
        Quant = self.env["stock.quant"]
        try:
            quant = Quant.search([
                ("product_id", "=", product.id),
                ("location_id", "=", location.id),
                ("lot_id", "=", False),
            ], limit=1)

            if quant:
                if quant.quantity != qty:
                    quant.with_context(inventory_mode=True).write({"inventory_quantity": qty})
                    quant.action_apply_inventory()
            else:
                q = Quant.with_context(inventory_mode=True).create({
                    "product_id": product.id,
                    "location_id": location.id,
                    "inventory_quantity": qty,
                })
                q.action_apply_inventory()
        except Exception as e:
            _logger.warning("Could not apply stock quant for %s at %s: %s", product.name, location.name, e)

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
        """Upsert account.tax from Tally Tax Ledger (GST, TDS, TCS, etc.)."""
        name = data.get("name")
        if not name:
            return False
        rate = float(data.get("rate_of_tax") or 0.0)
        if not rate:
            import re
            m = re.search(r"(\d+(?:\.\d+)?)\s*%", name)
            if m:
                rate = float(m.group(1))

        parent = (data.get("parent") or "").lower()
        tname_lower = name.lower()
        tax_type = "purchase" if any(k in parent or k in tname_lower for k in ("purchase", "inward", "creditor", "input")) else "sale"

        Tax = self.env["account.tax"]
        rec = Tax.search([
            ("name", "=ilike", name),
            ("company_id", "=", self.company.id)
        ], limit=1)

        vals = {
            "name": name,
            "amount": rate,
            "amount_type": "percent",
            "type_tax_use": tax_type,
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
        """Find or create matching account.tax in Odoo with Indian GST & TDS support."""
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
            tname_lower = tax_name.lower()

            if calc_rate > 0:
                domain = [
                    ("amount", "=", calc_rate),
                    ("amount_type", "=", "percent"),
                    ("type_tax_use", "=", tax_type),
                    ("company_id", "=", self.company.id),
                ]
                if "cgst" in tname_lower:
                    tax = Tax.search(domain + [("name", "ilike", "cgst")], limit=1)
                elif "sgst" in tname_lower or "utgst" in tname_lower:
                    tax = Tax.search(domain + [("name", "ilike", "sgst")], limit=1)
                elif "igst" in tname_lower:
                    tax = Tax.search(domain + [("name", "ilike", "igst")], limit=1)
                elif "tds" in tname_lower:
                    tax = Tax.search(domain + [("name", "ilike", "tds")], limit=1)
                elif "tcs" in tname_lower:
                    tax = Tax.search(domain + [("name", "ilike", "tcs")], limit=1)

                if not tax:
                    tax = Tax.search(domain, limit=1)

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
        """Generic handler for customer and vendor invoices/refunds with Indian GST, E-Way & IRN mapping."""
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
            if any(k in led_lower for k in ("cgst", "sgst", "igst", "gst", "tax", "vat", "duties", "tds", "tcs")):
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
                if led != partner_name and not any(k in led.lower() for k in ("cgst", "sgst", "igst", "gst", "tax", "vat", "duties", "tds", "tcs")):
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

        narration_parts = []
        if data.get("narration"):
            narration_parts.append(f"<p>{data['narration']}</p>")
        if data.get("eway_bill_no"):
            narration_parts.append(f"<p><b>E-Way Bill:</b> {data['eway_bill_no']} ({data.get('vehicle_no') or 'N/A'})</p>")
        if data.get("irn"):
            narration_parts.append(f"<p><b>IRN:</b> {data['irn']} (Ack: {data.get('ack_no') or 'N/A'})</p>")

        vals = {
            "move_type": move_type,
            "partner_id": partner.id if partner else False,
            "invoice_date": date_str,
            "date": date_str,
            "ref": data.get("reference") or vch_num,
            "narration": "".join(narration_parts) if narration_parts else False,
            "company_id": self.company.id,
            "journal_id": journal.id if journal else False,
        }

        # Indian Localization fields on Move
        if "l10n_in_state_id" in Move._fields and partner and partner.state_id:
            vals["l10n_in_state_id"] = partner.state_id.id
        if "l10n_in_gst_treatment" in Move._fields and partner and getattr(partner, "l10n_in_gst_treatment", False):
            vals["l10n_in_gst_treatment"] = partner.l10n_in_gst_treatment
        if data.get("eway_bill_no") and "l10n_in_ewaybill_number" in Move._fields:
            vals["l10n_in_ewaybill_number"] = data["eway_bill_no"]

        # Check cancelled / deleted state
        if data.get("is_cancelled") or data.get("is_deleted"):
            if move and move.state == "posted":
                try:
                    move.button_cancel()
                except Exception as e:
                    _logger.warning("Could not cancel move %s for deleted Tally voucher: %s", move.id, e)
            return move

        if move:
            if move.state == "draft":
                move.invoice_line_ids.unlink()
                vals["invoice_line_ids"] = lines
                move.write(vals)
        else:
            vals["invoice_line_ids"] = lines
            move = Move.create(vals)

        if move and move.state == "draft" and self.instance.auto_post:
            try:
                move.action_post()
            except Exception as e:
                _logger.info("Invoice auto-post skipped: %s", e)

        return move

    def _find_or_create_bank_journal(self, name):
        """Find or create matching account.journal for bank/cash ledger."""
        if not name:
            return False
        Journal = self.env["account.journal"]
        j = Journal.search([
            "|", ("name", "=ilike", name), ("default_account_id.name", "=ilike", name),
            ("company_id", "=", self.company.id)
        ], limit=1)
        if j:
            return j

        acc = self._get_or_create_account(name, default_type="asset_cash")
        j_type = "cash" if "cash" in name.lower() else "bank"
        # Generate code from initials/prefix
        words = "".join(c for c in name if c.isalnum())
        code_cand = (words[:4] or ("CSH" if j_type == "cash" else "BNK")).upper()
        code = code_cand
        idx = 1
        while Journal.search_count([("code", "=", code), ("company_id", "=", self.company.id)]):
            code = f"{code_cand[:3]}{idx}"
            idx += 1

        try:
            return Journal.create({
                "name": name,
                "type": j_type,
                "code": code,
                "default_account_id": acc.id if acc else False,
                "company_id": self.company.id,
            })
        except Exception:
            return self._get_or_create_journal(j_type)

    def _reconcile_payment_with_allocations(self, payment, bill_allocs):
        """Auto-reconcile payment move lines with allocated invoices/bills."""
        Move = self.env["account.move"]
        pay_lines = payment.move_id.line_ids.filtered(
            lambda l: l.account_id.account_type in ("asset_receivable", "liability_payable") and not l.reconciled
        )
        if not pay_lines:
            return

        for alloc in bill_allocs:
            inv_name = (alloc.get("name") or "").strip()
            if not inv_name:
                continue
            inv_move = Move.search([
                ("name", "=", inv_name),
                ("company_id", "=", self.company.id),
                ("state", "=", "posted"),
            ], limit=1) or Move.search([
                ("ref", "=", inv_name),
                ("company_id", "=", self.company.id),
                ("state", "=", "posted"),
            ], limit=1)

            if inv_move:
                inv_lines = inv_move.line_ids.filtered(
                    lambda l: l.account_id.account_type in ("asset_receivable", "liability_payable") and not l.reconciled
                )
                if inv_lines:
                    try:
                        (pay_lines + inv_lines).reconcile()
                    except Exception as e:
                        _logger.debug("Reconciliation failed for payment %s and invoice %s: %s", payment.id, inv_move.id, e)

    def _upsert_payment_receipt(self, data):
        """Upsert account.payment from Tally Receipt or Payment Voucher with invoice auto-reconciliation."""
        Payment = self.env["account.payment"]
        vch_type = data.get("voucher_type", "").lower()
        is_receipt = "receipt" in vch_type
        pay_type = "inbound" if is_receipt else "outbound"
        vch_num = data.get("voucher_number")
        date_str = data.get("date")

        partner_name = data.get("party_ledger")
        partner = self._get_or_create_partner(partner_name, is_supplier=not is_receipt)

        total_amount = 0.0
        bank_cash_ledger = None
        bill_allocs = []

        for le in data.get("ledger_entries", []):
            led = le.get("ledger", "")
            amt = abs(float(le.get("amount") or 0.0))
            if amt > total_amount:
                total_amount = amt
            if led != partner_name and not any(k in led.lower() for k in ("cgst", "sgst", "igst", "gst", "tax", "vat", "tds", "tcs", "discount")):
                bank_cash_ledger = led
            if le.get("bill_allocations"):
                bill_allocs.extend(le["bill_allocations"])

        journal = False
        if bank_cash_ledger:
            journal = self._find_or_create_bank_journal(bank_cash_ledger)
        if not journal:
            journal = self._get_or_create_journal("bank" if "bank" in (bank_cash_ledger or "").lower() else "cash")

        memo_parts = [vch_num]
        if data.get("cheque_no"):
            memo_parts.append(f"Chq: {data['cheque_no']}")

        vals = {
            "payment_type": pay_type,
            "partner_type": "customer" if is_receipt else "supplier",
            "partner_id": partner.id if partner else False,
            "amount": total_amount,
            "date": date_str,
            "memo": " · ".join(memo_parts),
            "journal_id": journal.id if journal else False,
            "company_id": self.company.id,
        }

        rec = Payment.search([
            ("memo", "=ilike", vch_num),
            ("payment_type", "=", pay_type),
            ("company_id", "=", self.company.id)
        ], limit=1)

        if rec:
            if rec.state == "draft":
                rec.write(vals)
        else:
            rec = Payment.create(vals)

        if rec and rec.state == "draft" and self.instance.auto_post:
            try:
                rec.action_post()
                if bill_allocs:
                    self._reconcile_payment_with_allocations(rec, bill_allocs)
            except Exception as e:
                _logger.info("Payment auto-post/reconcile skipped for %s: %s", rec.id, e)

        return rec

    def _upsert_contra_voucher(self, data):
        """Upsert Contra voucher (Cash <-> Bank or Bank <-> Bank transfer) into Odoo."""
        Move = self.env["account.move"]
        vch_num = data.get("voucher_number")
        date_str = data.get("date")

        ledger_entries = data.get("ledger_entries", [])
        if len(ledger_entries) < 2:
            return False

        lines = []
        for le in ledger_entries:
            led = le.get("ledger", "")
            amt = float(le.get("amount") or 0.0)
            account = self._get_or_create_account(led, default_type="asset_cash")
            debit = abs(amt) if amt < 0 else 0.0
            credit = abs(amt) if amt > 0 else 0.0
            lines.append((0, 0, {
                "name": f"Contra: {led}",
                "account_id": account.id if account else False,
                "debit": debit,
                "credit": credit,
            }))

        journal = self._get_or_create_journal("general")

        vals = {
            "move_type": "entry",
            "date": date_str,
            "ref": vch_num,
            "narration": data.get("narration") or f"<p>Tally Contra Voucher {vch_num}</p>",
            "company_id": self.company.id,
            "journal_id": journal.id if journal else False,
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

        if rec and rec.state == "draft" and self.instance.auto_post:
            try:
                rec.action_post()
            except Exception as e:
                _logger.info("Contra move auto-post skipped: %s", e)

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
