# -*- coding: utf-8 -*-
"""Sync Engine Service for TallyPrime <-> Odoo 18.

Handles:
- Orchestrating inbound Tally -> Odoo records (Masters & Vouchers)
- Orchestrating outbound Odoo -> Tally records into tally.sync.queue
- Identity mapping management (tally.mapping)
- Content hashing & echo-suppression
- Source of truth / conflict resolution
- Logging to tally.sync.log
"""
import hashlib
import re
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

try:
    from ..models.compat import move_uom_field
except ImportError:  # standalone parser/builder use without Odoo
    move_uom_field = None


# Tally's reserved (base) voucher types that carry accounting entries.
BASE_VOUCHER_ENTITY = {
    "sales": "sales",
    "purchase": "purchase",
    "receipt": "receipt",
    "payment": "payment",
    "journal": "journal",
    "contra": "contra",
    "credit note": "credit_note",
    "debit note": "debit_note",
    "stock journal": "stock_journal",
}
# Base types that never touch the books: orders, delivery/receipt notes,
# memorandum, optional/reversing, payroll, attendance and physical stock.
NON_ACCOUNTING_VOUCHER_TYPES = {
    "sales order", "purchase order", "delivery note", "receipt note", "rejections in",
    "rejections out", "memorandum", "reversing journal", "physical stock", "attendance",
    "payroll", "material in", "material out", "job work in order", "job work out order",
}


def voucher_type_to_entity(vch_type, type_parents=None):
    """Map a Tally voucher type (including user-defined types such as "Tax
    Invoice" whose parent is "Sales") to an entity code, or ``None`` when the
    voucher type is not an accounting document and must not be imported."""
    node = (vch_type or "").strip().lower()
    seen = set()
    while node and node not in seen:
        seen.add(node)
        if node in BASE_VOUCHER_ENTITY:
            return BASE_VOUCHER_ENTITY[node]
        if node in NON_ACCOUNTING_VOUCHER_TYPES:
            return None
        node = (type_parents or {}).get(node, "")
    if type_parents:
        return None
    # No voucher-type hierarchy available: conservative name heuristics.
    t = (vch_type or "").lower()
    if any(k in t for k in ("order", "delivery note", "receipt note", "rejection", "memorandum",
                            "physical", "reversing", "material", "attendance", "payroll", "job work")):
        return None
    for key, entity in (("stock journal", "stock_journal"), ("credit note", "credit_note"),
                        ("debit note", "debit_note"), ("contra", "contra"), ("receipt", "receipt"),
                        ("payment", "payment"), ("purchase", "purchase"), ("sale", "sales"),
                        ("journal", "journal")):
        if key in t:
            return entity
    return None


def compute_payload_hash(data):
    """Compute SHA-256 hash of a normalized JSON-serializable structure."""
    serialized = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class SyncEngine:
    VOUCHER_ENTITIES = {
        "sales", "credit_note", "purchase", "debit_note", "receipt",
        "payment", "journal", "contra", "opening_balance", "stock_journal",
    }
    # Tally documents (as opposed to masters) - one voucher per Odoo record.
    DOCUMENT_ENTITIES = VOUCHER_ENTITIES - {"opening_balance"}

    def __init__(self, env, instance, ledger_index=None, type_parents=None):
        # Run as the instance's company: account codes, partner receivable/payable
        # accounts and other company-dependent values are per company in Odoo 18+.
        self.env = env(context=dict(env.context, tally_sync_origin="tally", tally_no_sync=True,
                                    allowed_company_ids=[instance.company_id.id]), su=True)
        self.instance = instance
        self.company = instance.company_id
        # name -> {"party": bool, "tax": bool, "chain": [...]} from the Ledger master.
        self.ledger_index = ledger_index if ledger_index is not None else instance._get_ledger_index()
        self.type_parents = type_parents if type_parents is not None else instance._get_voucher_type_parents()
        self._mapping = self.env["tally.mapping"].browse()

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

    @staticmethod
    def _identity_of(rec):
        return {
            "guid": rec.get("guid"),
            "alterid": rec.get("alterid"),
            "master_id": rec.get("master_id"),
            "name": rec.get("name"),
            "voucher_type": rec.get("voucher_type"),
            "voucher_number": rec.get("voucher_number"),
            "date": rec.get("date") or False,
        }

    def _mapped(self, model):
        """The Odoo record already linked to the Tally object being imported."""
        m = self._mapping
        if m and m.odoo_model_name == model and m.odoo_res_id:
            return self.env[model].browse(m.odoo_res_id).exists()
        return self.env[model].browse()

    def _link_mapping(self, entity, rec, odoo_record):
        """Create/refresh the identity link after a successful import.

        Refuses to re-point a record that is already linked to a *different*
        Tally object: silently merging two Tally documents into one Odoo record
        would lose one of them.
        """
        Mapping = self.env["tally.mapping"]
        guid = (rec.get("guid") or "").strip()
        mapping = self._mapping
        other = Mapping.for_record(self.instance, entity, odoo_record._name, odoo_record.id)
        if other and other != mapping:
            if other.tally_guid and guid and other.tally_guid != guid:
                raise ValueError(_(
                    "Tally %(kind)s '%(label)s' (GUID %(guid)s) resolved to Odoo %(model)s #%(id)s, "
                    "which is already linked to Tally GUID %(other)s. Refusing to merge two Tally "
                    "objects into one Odoo record.") % {
                        "kind": entity, "label": rec.get("name") or rec.get("voucher_number"),
                        "guid": guid, "model": odoo_record._name, "id": odoo_record.id,
                        "other": other.tally_guid})
            if mapping:
                mapping.unlink()
            mapping = other
        vals = {
            "odoo_model_name": odoo_record._name,
            "odoo_res_id": odoo_record.id,
            "last_sync": fields.Datetime.now(),
            "state": "active",
            "is_orphan": False,
        }
        if not mapping:
            vals.update({"instance_id": self.instance.id, "entity": entity, "last_origin": "tally"})
            mapping = Mapping.create(vals)
        else:
            mapping.write(vals)
        if guid:
            mapping.bind_identity(self._identity_of(rec))
        elif not mapping.tally_name and rec.get("name"):
            mapping.tally_name = rec.get("name")
        if odoo_record._name in ("account.move", "account.payment", "stock.picking"):
            from ..models.tally_outbound import document_fingerprint
            mapping.odoo_fingerprint = document_fingerprint(odoo_record)
        return mapping

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
        quarantined = 0
        max_alterid = 0
        DeadLetter = self.env["tally.inbound.dead.letter"]
        Mapping = self.env["tally.mapping"]

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
            "opening_balance": self._upsert_opening_balance,
            "stock_journal": self._upsert_stock_journal,
        }

        handler = handler_map.get(entity)
        if not handler:
            _logger.warning("No sync handler for entity: %s", entity)
            return {"processed": 0, "skipped": len(records), "error": f"Unknown entity {entity}"}

        cfg_base = self.get_entity_config(entity)
        base_alterid = cfg_base.last_alterid if cfg_base else 0
        sot = cfg_base.source_of_truth if cfg_base else "tally"
        skipped = 0

        for rec in records:
            rec_alterid = int(rec.get("alterid") or 0)
            if rec_alterid > max_alterid:
                max_alterid = rec_alterid
            # Delta skip: AlterID only grows, so anything at or below the entity
            # watermark was already synced.
            if rec_alterid and base_alterid and rec_alterid <= base_alterid:
                skipped += 1
                continue
            if entity in self.DOCUMENT_ENTITIES and rec.get("is_optional"):
                skipped += 1
                continue

            dead = DeadLetter.for_record(self.instance, entity, rec)
            if dead and dead.state == "quarantined":
                quarantined += 1
                skipped += 1
                continue

            guid = rec.get("guid")
            mapping = Mapping.find_inbound(self.instance, entity, rec)
            if mapping and rec_alterid and mapping.tally_alterid and rec_alterid <= mapping.tally_alterid:
                # This Tally revision is already reflected in Odoo - typically the
                # read-back of a record Odoo itself just pushed.
                DeadLetter.resolve_record(self.instance, entity, rec)
                skipped += 1
                continue
            if mapping and mapping.last_origin == "odoo" and not mapping.tally_guid:
                # First read-back of an Odoo push whose binding did not complete:
                # link Tally's identity instead of importing a duplicate.
                mapping.bind_identity(self._identity_of(rec))
                DeadLetter.resolve_record(self.instance, entity, rec)
                skipped += 1
                continue
            if mapping and sot == "odoo":
                # Odoo owns this entity: record the Tally revision, keep Odoo's data.
                mapping.bind_identity(self._identity_of(rec))
                self.env["tally.sync.log"].log(
                    self.instance, "tally_to_odoo", entity, "warning",
                    _("Tally change to '%s' ignored: Odoo is the source of truth for %s.") % (
                        rec.get("name") or rec.get("voucher_number"), entity),
                    tally_guid=guid)
                DeadLetter.resolve_record(self.instance, entity, rec)
                skipped += 1
                continue

            try:
                with self.env.cr.savepoint():
                    self._mapping = mapping
                    odoo_record = handler(rec)
                    if odoo_record:
                        processed += 1
                        self._link_mapping(entity, rec, odoo_record)
                        self._maybe_autopost(entity, odoo_record)
                        DeadLetter.resolve_record(self.instance, entity, rec)
                        if getattr(self.instance, "verbose_logging", True):
                            nm = (rec.get("name") or rec.get("voucher_number")
                                  or odoo_record.display_name)
                            self.env["tally.sync.log"].log(
                                self.instance, "tally_to_odoo", entity, "success",
                                _("Imported %s") % nm, record_name=nm,
                                odoo_model_name=odoo_record._name, odoo_res_id=odoo_record.id,
                                tally_guid=guid, record_count=1)
                    else:
                        skipped += 1
            except Exception as e:
                dead = DeadLetter.record_failure(self.instance, entity, rec, e)
                is_quarantined = dead.state == "quarantined"
                if is_quarantined:
                    quarantined += 1
                else:
                    errors += 1
                _logger.exception("Error upserting %s: %s", entity, e)
                try:
                    label = rec.get("name") or rec.get("voucher_number")
                    if is_quarantined:
                        msg = _("QUARANTINED after %s attempts: %s '%s' — %s") % (
                            dead.attempts, entity, label, str(e))
                    else:
                        msg = f"Failed upserting {entity} {label}: {str(e)}"
                    self.env["tally.sync.log"].log(
                        self.instance, "tally_to_odoo", entity,
                        "warning" if is_quarantined else "error", msg,
                        detail=str(rec), tally_guid=guid,
                    )
                except Exception:
                    pass
            finally:
                self._mapping = Mapping.browse()

        # Advance AlterID watermark
        cfg = self.get_entity_config(entity)
        # Never advance past a failed record. Re-reading successful records is safe and
        # preferable to permanently losing a failed accounting object.
        if cfg and errors == 0 and (alterid or max_alterid):
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

        return {"processed": processed, "errors": errors,
                "quarantined": quarantined, "skipped": skipped,
                "watermark": cfg.last_alterid if cfg else max_alterid}

    def process_vouchers(self, vouchers, alterid=None):
        """Group a mixed list of parsed vouchers by entity and dispatch each group."""
        groups = {}
        ignored = 0
        for v in vouchers or []:
            entity = voucher_type_to_entity(v.get("voucher_type"), self.type_parents)
            if not entity:
                ignored += 1
                continue
            groups.setdefault(entity, []).append(v)
        if ignored:
            self.env["tally.sync.log"].log(
                self.instance, "tally_to_odoo", False, "success",
                _("%s non-accounting voucher(s) (orders, notes, memorandum...) not imported.") % ignored)
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
    # LEDGER CLASSIFICATION HELPERS
    # =========================================================================

    _TAX_WORD = re.compile(r"(?<![a-z])(cgst|sgst|igst|utgst|gst|vat|cess|tds|tcs|duties)(?![a-z])")

    def _ledger_info(self, name):
        return (self.ledger_index or {}).get((name or "").strip().lower()) or {}

    def _is_tax_ledger(self, name):
        """A ledger is a tax ledger when Tally files it under Duties & Taxes.
        Name patterns are only a fallback and match whole words, so "Processing
        Fees" or "Renovation" are never mistaken for CESS/VAT."""
        info = self._ledger_info(name)
        if info:
            return bool(info.get("tax"))
        if self.env["tally.mapping"].search_count([
                ("instance_id", "=", self.instance.id), ("entity", "=", "tax"),
                ("tally_name", "=", name)]):
            return True
        return bool(self._TAX_WORD.search((name or "").lower()))

    def _is_party_ledger(self, name):
        info = self._ledger_info(name)
        if info:
            return bool(info.get("party"))
        return bool(self.env["tally.mapping"].search_count([
            ("instance_id", "=", self.instance.id), ("entity", "=", "ledger"),
            ("tally_name", "=", name)]))

    def _is_bank_ledger(self, name):
        chain = self._ledger_info(name).get("chain") or []
        if chain:
            return any(g in ("bank accounts", "cash-in-hand", "bank od a/c", "bank occ a/c") for g in chain)
        lower = (name or "").lower()
        return "bank" in lower or "cash" in lower

    def _party_for_ledger(self, name):
        """Partner linked to a Tally party ledger (by mapping, then by name)."""
        m = self.env["tally.mapping"].search([
            ("instance_id", "=", self.instance.id), ("entity", "=", "ledger"),
            ("tally_name", "=", name), ("odoo_model_name", "=", "res.partner")], limit=1)
        if m:
            partner = self.env["res.partner"].browse(m.odoo_res_id).exists()
            if partner:
                return partner
        return False

    def _account_for_ledger(self, name, default_type="expense"):
        """Odoo account for a Tally general ledger: mapping first, then name.

        Tally's reserved "Profit & Loss A/c" ledger holds accumulated profit: it is
        equity in Odoo, never an expense (which would distort Odoo's P&L)."""
        if (name or "").strip().lower() in ("profit & loss a/c", "profit and loss a/c") or \
                self._ledger_info(name).get("reserved", "").lower() == "profit & loss a/c":
            default_type = "equity"
            account = self._get_or_create_account(name, default_type=default_type)
            if account.account_type not in ("equity", "equity_unaffected"):
                account.account_type = "equity"
            return account
        m = self.env["tally.mapping"].search([
            ("instance_id", "=", self.instance.id), ("entity", "=", "account_ledger"),
            ("tally_name", "=", name), ("odoo_model_name", "=", "account.account")], limit=1)
        if m:
            account = self.env["account.account"].browse(m.odoo_res_id).exists()
            if account:
                return account
        chain = self._ledger_info(name).get("chain") or []
        if chain:
            default_type = self._map_tally_group_to_account_type(chain)
        return self._get_or_create_account(name, default_type=default_type)

    def _line_target(self, name, is_supplier=False, default_type="expense"):
        """Resolve a voucher ledger line to ``(account, partner)``.

        Party ledgers post to the partner's receivable/payable account with the
        partner set; creating an expense account named after a customer would
        corrupt both the balance sheet and the partner ledger.
        """
        partner = self._party_for_ledger(name)
        if not partner and self._is_party_ledger(name):
            chain = self._ledger_info(name).get("chain") or []
            partner = self._get_or_create_partner(
                name, is_supplier=is_supplier or "sundry creditors" in chain)
        if partner:
            chain = self._ledger_info(name).get("chain") or []
            supplier = "sundry creditors" in chain or (
                not chain and partner.supplier_rank and not partner.customer_rank)
            account = (partner.property_account_payable_id if supplier
                       else partner.property_account_receivable_id)
            return account, partner
        if self._is_bank_ledger(name):
            journal = self._find_or_create_bank_journal(name)
            if journal and journal.default_account_id:
                return journal.default_account_id, False
        return self._account_for_ledger(name, default_type=default_type), False

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
        rec = self._mapped("res.currency")

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
        rec = self._mapped("account.group") or Group.search([
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
        rec = self._mapped("account.account")

        # 2. Search existing by name/code scoped to company
        if not rec:
            domain = [("name", "=ilike", name)] + self._account_company_domain()
            rec = Account.search(domain, limit=1)

        # Map Tally parent group to Odoo account_type
        account_type = self._map_tally_group_to_account_type(data.get("group_chain") or parent)

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
        rec = self._mapped("res.partner")

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

        # Smart Address Parsing (multi-split across street, street2, city, zip)
        street = ""
        street2 = ""
        city = ""
        zip_code = (data.get("pincode") or "").strip()
        addresses = data.get("addresses", [])
        if addresses:
            cleaned_addrs = [a.strip() for a in addresses if a and a.strip()]
            if len(cleaned_addrs) == 1:
                street = cleaned_addrs[0]
            elif len(cleaned_addrs) == 2:
                street = cleaned_addrs[0]
                street2 = cleaned_addrs[1]
            elif len(cleaned_addrs) >= 3:
                street = cleaned_addrs[0]
                street2 = cleaned_addrs[1]
                import re
                for extra in cleaned_addrs[2:]:
                    m = re.search(r"\b\d{6}\b", extra)
                    if m and not zip_code:
                        zip_code = m.group(0)
                    if not city:
                        cand = re.sub(r"\b\d{6}\b", "", extra).strip(", ")
                        if cand and not any(s.lower() in cand.lower() for s in ("india", "pin", "state")):
                            city = cand

        vals = {
            "name": name,
            "vat": gstin or False,
            "street": street or False,
            "street2": street2 or False,
            "city": city or False,
            "state_id": state_id,
            "country_id": country_id,
            "zip": zip_code or False,
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
        rec = self._mapped("uom.uom") or Uom.search([("name", "=ilike", name)], limit=1)
        if rec and rec.name != name:
            rec.name = name
        if not rec:
            vals = {"name": name}
            # Odoo 20 removed per-unit rounding (precision is global).
            if "rounding" in Uom._fields:
                vals["rounding"] = 1.0 / (10 ** int(data.get("decimal_places") or 0))
            # Odoo 18 requires every UoM to belong to a category and permits
            # only one reference UoM per category. A Tally simple unit does
            # not carry a safe conversion ratio to an existing Odoo category,
            # so give each imported unit its own category. Odoo 19 removed
            # this field, therefore the guard also keeps the code portable.
            if "category_id" in Uom._fields:
                category_name = "Tally unit: %s" % name
                category = self.env["uom.category"].search([
                    ("name", "=ilike", category_name),
                ], limit=1)
                if not category:
                    category = self.env["uom.category"].create({
                        "name": category_name,
                    })
                vals["category_id"] = category.id
            rec = Uom.create(vals)
        return rec

    def _upsert_stock_group(self, data):
        """Upsert product.category from Tally <STOCKGROUP>."""
        name = data.get("name")
        if not name:
            return False
        Category = self.env["product.category"]
        rec = self._mapped("product.category") or Category.search([("name", "=", name)], limit=1)
        parent_id = False
        if data.get("parent") and data["parent"] != "Primary":
            p = Category.search([("name", "=", data["parent"])], limit=1)
            parent_id = p.id if p else False
        if rec:
            rec.write({"name": name, "parent_id": parent_id})
        if not rec:
            parent_id = False
            if data.get("parent") and data["parent"] != "Primary":
                p = Category.search([("name", "=", data["parent"])], limit=1)
                parent_id = p.id if p else False
            rec = Category.create({"name": name, "parent_id": parent_id})
        return rec

    def _upsert_stock_item(self, data):
        """Upsert product.product from Tally <STOCKITEM> with barcode, UoM, rate and stock quants."""
        name = data.get("name")
        if not name:
            return False
        Product = self.env["product.product"]

        # 1. Search existing by mapping GUID
        rec = self._mapped("product.product")

        # 2. Search existing by barcode / default_code or name scoped to company
        barcode = (data.get("barcode") or "").strip()
        if not rec and barcode:
            rec = Product.search([
                "|", ("barcode", "=", barcode), ("default_code", "=", barcode),
                ("company_id", "in", (False, self.company.id))
            ], limit=1)

        if not rec:
            rec = Product.search([
                ("name", "=ilike", name),
                ("company_id", "in", (False, self.company.id))
            ], limit=1)

        uom_name = data.get("base_uom", "Units")
        uom = self.env["uom.uom"].search([("name", "=ilike", uom_name)], limit=1)
        if not uom:
            uom = self.env.ref("uom.product_uom_unit", raise_if_not_found=False) or self.env["uom.uom"].search([], limit=1)

        parent_grp = (data.get("parent_group") or "").lower()
        is_service = any(k in parent_grp or k in name.lower() for k in ("service", "consulting", "freight", "labour", "fee"))
        prod_type = "service" if is_service else "consu"

        rate = float(data.get("rate") or data.get("opening_rate") or data.get("closing_rate") or 0.0)

        vals = {
            "name": name,
            "type": prod_type,
            "uom_id": uom.id if uom else False,
            "company_id": self.company.id,
        }
        parent_group = (data.get("parent_group") or "").strip()
        if parent_group and parent_group.lower() != "primary":
            category = self.env["product.category"].search([
                ("name", "=ilike", parent_group),
            ], limit=1)
            if not category:
                category = self.env["product.category"].create({"name": parent_group})
            vals["categ_id"] = category.id
        if barcode:
            vals["barcode"] = barcode
        part_no = (data.get("part_no") or "").strip()
        if part_no or barcode:
            vals["default_code"] = part_no or barcode
        if rate > 0:
            vals["standard_price"] = rate
        if float(data.get("sale_price") or 0.0) > 0:
            vals["list_price"] = float(data["sale_price"])

        if "is_storable" in Product._fields and prod_type != "service":
            vals["is_storable"] = True
        # Check HSN code
        if data.get("hsn_code") and "l10n_in_hsn_code" in Product._fields:
            vals["l10n_in_hsn_code"] = data["hsn_code"]

        if rec:
            rec.write(vals)
        else:
            rec = Product.create(vals)

        # Apply stock on-hand quantity matching Tally closing/opening balance (for physical inventory items)
        if prod_type != "service":
            target_qty = float(data.get("quantity") or data.get("closing_balance") or data.get("opening_balance") or 0.0)
            self._apply_stock_quantities(rec, target_qty, data.get("batch_allocations"))

        return rec


    def _apply_stock_quantities(self, product, target_qty, batch_allocations=None):
        """Apply physical on-hand stock quantities to Odoo stock.quant."""
        if not product or not hasattr(product, "qty_available"):
            return
        valuation = getattr(product.categ_id, "property_valuation", False)
        if valuation == "real_time" and not self.instance.sync_automated_valuation_stock:
            self.env["tally.sync.log"].log(
                self.instance, "tally_to_odoo", "stock_item", "warning",
                _("Quantity adjustment skipped for %s: its category uses automated valuation. "
                  "Enable 'Adjust Automated-Valuation Stock' only when stock value is not also "
                  "being migrated through opening balances.") % product.display_name,
                record_name=product.display_name,
                odoo_model_name=product._name, odoo_res_id=product.id)
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
            # A direct Tally stock-item export reports the company's total
            # closing balance, not the balance of Odoo's default warehouse.
            # Keep quantities already recovered into other internal locations
            # (for example by a Stock Journal) and put only the residual in the
            # default location.  This makes repeated master pulls idempotent.
            other_internal_qty = sum(Quant.search([
                ("product_id", "=", product.id),
                ("location_id", "!=", default_loc.id),
                ("location_id.usage", "=", "internal"),
                ("company_id", "=", self.company.id),
            ]).mapped("quantity"))
            self._set_location_quant(
                product, default_loc, float(target_qty or 0.0) - other_internal_qty)

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
            elif qty:
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
        rec = self._mapped("account.analytic.account") or Analytic.search([
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
        if not name:
            return False
        Location = self.env["stock.location"]
        if name == "Main Location":
            warehouse = self.env["stock.warehouse"].search([
                ("company_id", "=", self.company.id),
            ], limit=1)
            return warehouse.lot_stock_id or Location.search([
                ("usage", "=", "internal"),
                ("company_id", "in", (False, self.company.id)),
            ], limit=1)
        rec = self._mapped("stock.location") or Location.search([
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
        rec = self._mapped("account.tax") or Tax.search([
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
        self._ensure_tax_account(rec, name, tax_type)
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

    def _ensure_tax_account(self, tax, ledger_name, tax_type):
        """Post a Tally-named tax to the account of its Tally tax ledger.

        A tax repartition line without an account makes Odoo book the tax on the
        base line's account, i.e. GST would be added to Sales/Purchases instead
        of a Duties & Taxes account.
        """
        # The combined ``repartition_line_ids`` reads back empty right after
        # create on Odoo 19; the per-document fields are always populated.
        lines = (tax.invoice_repartition_line_ids | tax.refund_repartition_line_ids).filtered(
            lambda l: l.repartition_type == "tax" and not l.account_id)
        if lines:
            account = self._account_for_ledger(
                ledger_name, default_type="liability_current" if tax_type == "sale" else "asset_current")
            lines.write({"account_id": account.id})

    def _find_or_create_tax(self, tax_name, rate=0.0, tax_type="sale"):
        """Find or create matching account.tax in Odoo with Indian GST & TDS support."""
        Tax = self.env["account.tax"]
        tax = Tax.search([
            ("name", "=ilike", tax_name),
            ("type_tax_use", "=", tax_type),
            ("company_id", "=", self.company.id),
        ], limit=1)
        if tax:
            self._ensure_tax_account(tax, tax_name, tax_type)
        if not tax:
            import re
            m = re.search(r"(\d+(?:\.\d+)?)\s*%", tax_name)
            calc_rate = float(m.group(1)) if m else rate
            tname_lower = tax_name.lower()

            # Borrowing an existing Odoo tax by rate/component is only right when the
            # company maps Tally onto its own chart of taxes. Otherwise every Tally
            # tax ledger gets a tax (and account) of its own, so per-ledger GST
            # balances stay identical in both books.
            if calc_rate > 0 and getattr(self.instance, "coa_mode", "import") == "map":
                domain = [
                    ("amount", "=", calc_rate),
                    ("amount_type", "=", "percent"),
                    ("type_tax_use", "=", tax_type),
                    ("company_id", "=", self.company.id),
                ]
                # A component ledger (CGST/SGST/IGST/cess/TDS/TCS) must map to a tax of
                # the same component. Matching is done on whole words in Python: an
                # ORM ``ilike`` for "utgst" matched "Output CGST" on Odoo 19, and a
                # rate-only fallback once mapped SGST onto the CGST tax.
                component = next((k for k in ("cgst", "sgst", "utgst", "igst", "cess", "tds", "tcs")
                                  if re.search(r"(?<![a-z])%s(?![a-z])" % k, tname_lower)), None)
                candidates = Tax.search(domain)
                if component:
                    accepted = ("sgst", "utgst") if component in ("sgst", "utgst") else (component,)
                    tax = candidates.filtered(lambda t: any(
                        re.search(r"(?<![a-z])%s(?![a-z])" % k, (t.name or "").lower()) for k in accepted))[:1]
                else:
                    tax = candidates.filtered(lambda t: not re.search(
                        r"(?<![a-z])(cgst|sgst|utgst|igst|cess|tds|tcs)(?![a-z])", (t.name or "").lower()))[:1]

            if not tax:
                tax_vals = {
                    "name": tax_name,
                    "amount": calc_rate,
                    "amount_type": "percent",
                    "type_tax_use": tax_type,
                    "company_id": self.company.id,
                }
                # Tax Group lookup/creation
                TaxGroup = self.env["account.tax.group"]
                grp_name = "GST"
                if "cgst" in tname_lower:
                    grp_name = "CGST"
                elif "sgst" in tname_lower or "utgst" in tname_lower:
                    grp_name = "SGST"
                elif "igst" in tname_lower:
                    grp_name = "IGST"
                elif "tds" in tname_lower:
                    grp_name = "TDS"
                elif "tcs" in tname_lower:
                    grp_name = "TCS"
                elif "cess" in tname_lower:
                    grp_name = "Cess"

                tg = TaxGroup.search([("name", "=ilike", grp_name), ("company_id", "in", (False, self.company.id))], limit=1)
                if not tg:
                    try:
                        tg = TaxGroup.create({"name": grp_name, "company_id": self.company.id})
                    except Exception:
                        tg = TaxGroup.search([], limit=1)
                if tg:
                    tax_vals["tax_group_id"] = tg.id
                tax = Tax.create(tax_vals)
                self._ensure_tax_account(tax, tax_name, tax_type)
        return tax

    # ------------------------------------------------------------------ helpers
    def _is_mapped_elsewhere(self, record, entities):
        return bool(self.env["tally.mapping"].search_count([
            ("instance_id", "=", self.instance.id), ("entity", "in", list(entities)),
            ("odoo_model_name", "=", record._name), ("odoo_res_id", "=", record.id)]))

    def _retire_other_model(self, model):
        """A Tally voucher that changed shape (e.g. a simple receipt edited into a
        multi-ledger receipt) moves between account.payment and account.move.
        Cancel the previous Odoo record so the document is never counted twice."""
        m = self._mapping
        if m and m.odoo_model_name and m.odoo_model_name != model and m.odoo_res_id:
            old = self.env[m.odoo_model_name].browse(m.odoo_res_id).exists()
            if old:
                self._cancel_record(old)

    def _cancel_record(self, record):
        if not record or record.state == "cancel":
            return
        if record._name == "account.payment":
            if record.state != "draft":
                record.action_draft()
            record.action_cancel()
            return
        if record.state == "posted":
            record.button_draft()
        record.button_cancel()

    def _reopen_move(self, move):
        """Reset a posted move to draft so a Tally amendment can be applied.

        Returns the counterpart lines it was reconciled with so the link can be
        restored after re-posting. Lock dates / hash integrity raise a UserError,
        which surfaces as a sync error instead of a silent divergence.
        """
        counterparts = self.env["account.move.line"]
        for line in move.line_ids.filtered(
                lambda l: l.account_id.account_type in ("asset_receivable", "liability_payable")):
            counterparts |= line.matched_debit_ids.debit_move_id | line.matched_credit_ids.credit_move_id
        counterparts -= move.line_ids
        move.button_draft()
        return counterparts

    def _repost(self, move, counterparts=None, force=False):
        if move.state != "draft" or not (force or self.instance.auto_post):
            return
        move.action_post()
        if counterparts:
            try:
                with self.env.cr.savepoint():
                    pending = (move.line_ids | counterparts).filtered(
                        lambda l: l.account_id.account_type in ("asset_receivable", "liability_payable")
                        and not l.reconciled)
                    for account in pending.account_id:
                        group = pending.filtered(lambda l: l.account_id == account)
                        if len(group) > 1:
                            group.reconcile()
            except Exception as e:
                _logger.info("Could not restore reconciliation for %s: %s", move.display_name, e)

    def _adopt_move(self, move_type, partner, date, refs, amount):
        """Brownfield only: link an *unmapped* Odoo document that is clearly the
        same Tally voucher (same type, partner, date, reference and total).
        Ambiguous candidates are never adopted - a new document is created."""
        refs = [r for r in refs if r]
        if not refs or not date:
            return self.env["account.move"]
        domain = [("move_type", "=", move_type), ("company_id", "=", self.company.id),
                  ("state", "!=", "cancel"), ("date", "=", date),
                  "|", ("ref", "in", refs), ("name", "in", refs)]
        if partner:
            domain.append(("partner_id", "=", partner.id))
        candidates = self.env["account.move"].search(domain).filtered(
            lambda m: not self._is_mapped_elsewhere(m, self.DOCUMENT_ENTITIES)
            and self.company.currency_id.compare_amounts(m.amount_total, amount) == 0)
        return candidates if len(candidates) == 1 else self.env["account.move"]

    def _matches_tally(self, move, party_amount, tax_entries):
        """True when the Odoo-computed document equals the Tally voucher: same
        total and, per Tally tax ledger, the same tax amount."""
        currency = self.company.currency_id
        if currency.compare_amounts(move.amount_total, party_amount) != 0:
            return False
        tax_lines = move.line_ids.filtered(lambda l: l.tax_line_id)
        expected = {}
        for _led, amt, tax in tax_entries:
            if not tax:
                return False
            expected[tax.id] = expected.get(tax.id, 0.0) + abs(amt)
        got = {}
        for line in tax_lines:
            got[line.tax_line_id.id] = got.get(line.tax_line_id.id, 0.0) + abs(line.amount_currency)
        if set(got) != set(expected):
            return False
        return all(currency.compare_amounts(got[k], expected[k]) == 0 for k in expected)

    # ------------------------------------------------------------ invoices
    def _upsert_invoice_move(self, data, move_type="out_invoice"):
        """Customer/vendor invoices and refunds.

        Item lines post to the Tally ledger each item is allocated to; every other
        non-party, non-tax ledger (freight, discount, round-off...) becomes its own
        line with the sign Tally recorded. The party ledger total stays
        authoritative: any residual (e.g. a GST computation Odoo cannot express)
        is booked on a visible reconciliation line.
        """
        Move = self.env["account.move"]
        vch_num = data.get("voucher_number")
        date_str = data.get("date")
        partner_name = data.get("party_ledger")
        is_purchase_side = move_type in ("in_invoice", "in_refund")
        if partner_name and self._ledger_info(partner_name) and not self._is_party_ledger(partner_name):
            # Cash/bank sale or purchase (Dr Cash / Cr Sales): there is no customer
            # or vendor to invoice, so the voucher is booked line for line.
            return self._upsert_journal_voucher(data)
        partner = self._party_for_ledger(partner_name) or self._get_or_create_partner(
            partner_name, is_supplier=is_purchase_side)
        tax_type = "purchase" if is_purchase_side else "sale"
        default_acc_type = "expense" if is_purchase_side else "income"
        # +1 when a Tally credit (positive amount) increases this document's total.
        line_sign = 1.0 if move_type in ("out_invoice", "in_refund") else -1.0

        entries = data.get("ledger_entries") or []
        inv_entries = data.get("inventory_entries") or []
        party_amount = abs(sum(float(le.get("amount") or 0.0)
                               for le in entries if le.get("ledger") == partner_name))
        item_ledgers = {ie.get("account_ledger") for ie in inv_entries if ie.get("account_ledger")}

        tax_ids, tax_signatures, other_entries, tax_entries = [], [], [], []
        for le in entries:
            led = le.get("ledger") or ""
            amt = float(le.get("amount") or 0.0)
            if led == partner_name or not amt:
                continue
            if self._is_tax_ledger(led):
                tax_rec = self._find_or_create_tax(led, tax_type=tax_type)
                tax_entries.append((led, amt, tax_rec))
                if tax_rec and tax_rec.id not in tax_ids:
                    tax_ids.append(tax_rec.id)
                    lower = led.lower()
                    tax_signatures.append((
                        next((k for k in ("cgst", "sgst", "igst", "tds", "tcs", "cess") if k in lower), "tax"),
                        float(tax_rec.amount)))
                continue
            if inv_entries:
                if led in item_ledgers:
                    continue
                chain = self._ledger_info(led).get("chain") or []
                if not item_ledgers and (
                        any(g in ("sales accounts", "purchase accounts") for g in chain)
                        or (not chain and led.lower() in ("sales account", "purchase account",
                                                          "sales", "purchase", "sales accounts",
                                                          "purchase accounts"))):
                    continue
            other_entries.append((led, amt))

        mixed_tax_rates = any(
            len({rate for kind, rate in tax_signatures if kind == component}) > 1
            for component in {kind for kind, _rate in tax_signatures})
        default_account = self._get_or_create_account(
            "Purchase Account" if is_purchase_side else "Sales Account", default_type=default_acc_type)

        price_digits = self.env["decimal.precision"].precision_get("Product Price")
        lines, exact_lines = [], []
        for ie in inv_entries:
            product = self._get_or_create_product(ie.get("item"))
            qty = abs(float(ie.get("qty") or 0.0)) or 1.0
            amount = abs(float(ie.get("amount") or 0.0))
            rate = abs(float(ie.get("rate") or 0.0))
            disc = float(ie.get("discount") or 0.0)
            if rate and abs(rate * qty * (1 - disc / 100.0) - amount) <= 0.01:
                price, discount = rate, disc
            else:
                price, discount = amount / qty, 0.0
            account = (self._account_for_ledger(ie["account_ledger"], default_type=default_acc_type)
                       if ie.get("account_ledger") else default_account)
            item_tax_ids = []
            item_gst_rate = abs(float(ie.get("gst_rate") or 0.0))
            if item_gst_rate:
                interstate = bool(partner and partner.state_id and self.company.state_id
                                  and partner.state_id != self.company.state_id)
                if interstate:
                    item_tax_ids = self._find_or_create_tax(
                        "IGST %.2f%%" % item_gst_rate, rate=item_gst_rate, tax_type=tax_type).ids
                else:
                    half = item_gst_rate / 2.0
                    item_tax_ids = (self._find_or_create_tax("CGST %.2f%%" % half, rate=half, tax_type=tax_type)
                                    | self._find_or_create_tax("SGST %.2f%%" % half, rate=half, tax_type=tax_type)).ids
            elif tax_ids and not mixed_tax_rates:
                item_tax_ids = tax_ids
            item_vals = {
                "product_id": product.id if product else False,
                "account_id": account.id if account else False,
                "name": ie.get("item") or "Item",
                "quantity": qty,
                "price_unit": price,
                "discount": discount,
            }
            if abs(round(round(price, price_digits) * qty * (1 - discount / 100.0), 2) - amount) > 0.005:
                # The unit price cannot carry Tally's line amount at Odoo's price
                # precision (e.g. 100 for 3 units); keep the amount exact instead.
                item_vals.update({"quantity": 1.0, "price_unit": amount, "discount": 0.0,
                                  "name": "%s (%s x %s)" % (ie.get("item") or "Item", qty, rate or price)})
            # Explicit: never let product/company default taxes leak in.
            lines.append((0, 0, dict(item_vals, tax_ids=[(6, 0, item_tax_ids)])))
            exact_lines.append((0, 0, dict(item_vals, tax_ids=[(6, 0, [])])))

        for led, amt in other_entries:
            account, _line_partner = self._line_target(led, is_supplier=is_purchase_side,
                                                       default_type=default_acc_type)
            chain = self._ledger_info(led).get("chain") or []
            taxable = (not inv_entries and tax_ids and not mixed_tax_rates and (
                any(g in ("sales accounts", "purchase accounts") for g in chain)
                or (not chain and "round" not in led.lower())))
            other_vals = {
                "name": led,
                "account_id": account.id if account else default_account.id,
                "quantity": 1,
                "price_unit": line_sign * amt,
            }
            lines.append((0, 0, dict(other_vals, tax_ids=[(6, 0, tax_ids if taxable else [])])))
            exact_lines.append((0, 0, dict(other_vals, tax_ids=[(6, 0, [])])))
        # Exact representation: each Tally tax ledger as its own line on the
        # account of that ledger.
        for led, amt, _tax in tax_entries:
            tax_account = self._account_for_ledger(
                led, default_type="asset_current" if is_purchase_side else "liability_current")
            exact_lines.append((0, 0, {"name": led, "account_id": tax_account.id, "quantity": 1,
                                       "price_unit": line_sign * amt, "tax_ids": [(6, 0, [])]}))

        journal = self._get_or_create_journal("purchase" if is_purchase_side else "sale")
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
        if is_purchase_side and "payment_reference" in Move._fields and vch_num:
            vals["payment_reference"] = vch_num
        if partner and partner.state_id and self.company.state_id:
            fp_domain = [("company_id", "in", (False, self.company.id))]
            key = "inter" if partner.state_id.id != self.company.state_id.id else "intra"
            fp = self.env["account.fiscal.position"].search(fp_domain + [("name", "ilike", key)], limit=1)
            if fp:
                vals["fiscal_position_id"] = fp.id
        if "l10n_in_state_id" in Move._fields and partner and partner.state_id:
            vals["l10n_in_state_id"] = partner.state_id.id
        if "l10n_in_gst_treatment" in Move._fields and partner and getattr(partner, "l10n_in_gst_treatment", False):
            vals["l10n_in_gst_treatment"] = partner.l10n_in_gst_treatment
        if data.get("eway_bill_no") and "l10n_in_ewaybill_number" in Move._fields:
            vals["l10n_in_ewaybill_number"] = data["eway_bill_no"]

        self._retire_other_model("account.move")
        move = self._mapped("account.move") or self._adopt_move(
            move_type, partner, date_str, [data.get("reference"), vch_num], party_amount)

        if data.get("is_cancelled") or data.get("is_deleted"):
            if move:
                self._cancel_record(move)
                return move
            return False

        counterparts = None
        was_posted = False
        if move:
            if move.state == "cancel":
                move.button_draft()
            elif move.state == "posted":
                was_posted = True
                counterparts = self._reopen_move(move)
            move.invoice_line_ids.unlink()
            vals["invoice_line_ids"] = lines
            move.write(vals)
        else:
            vals["invoice_line_ids"] = lines
            move = Move.create(vals)

        if not self._matches_tally(move, party_amount, tax_entries):
            # Odoo's tax computation cannot reproduce this voucher (GST on expense
            # ledgers, custom rates, per-line rounding...): book Tally's exact lines.
            move.invoice_line_ids.unlink()
            move.write({"invoice_line_ids": exact_lines})
        difference = self.company.currency_id.round(party_amount - move.amount_total)
        if party_amount and difference:
            _logger.warning("Tally voucher %s still differs by %s after exact import", vch_num, difference)
            adjustment_account = self._get_or_create_account(
                "Tally Voucher Reconciliation", default_type=default_acc_type)
            self.env["account.move.line"].create({
                "move_id": move.id,
                "name": _("Tally total reconciliation"),
                "account_id": adjustment_account.id,
                "quantity": 1.0,
                "price_unit": difference,
                "tax_ids": [(6, 0, [])],
            })

        try:
            move.message_post(
                body=_("Synced from Tally voucher %s (Type: %s, Date: %s)") % (
                    vch_num or move.name, data.get("voucher_type"), date_str),
                message_type="notification")
        except Exception:
            pass
        self._repost(move, counterparts, force=was_posted)
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
        """Receipt / Payment voucher.

        Only the canonical shape - one party ledger against one bank/cash ledger
        - becomes an ``account.payment``. Anything else (expenses paid directly,
        TDS deducted at source, several parties, bank charges) is imported as a
        journal entry so every Tally ledger line is preserved exactly.
        """
        entries = [le for le in (data.get("ledger_entries") or []) if float(le.get("amount") or 0.0)]
        party_name = data.get("party_ledger")
        party_lines = [le for le in entries if le.get("ledger") == party_name]
        other_lines = [le for le in entries if le.get("ledger") != party_name]
        simple = (party_name and party_lines and len(other_lines) == 1
                  and self._is_party_ledger(party_name)
                  and self._is_bank_ledger(other_lines[0].get("ledger")))
        if not simple:
            return self._upsert_journal_voucher(data)

        Payment = self.env["account.payment"]
        party_amount = sum(float(le.get("amount") or 0.0) for le in party_lines)
        # Tally debits are negative: crediting the party means money came in.
        pay_type = "inbound" if party_amount > 0 else "outbound"
        chain = self._ledger_info(party_name).get("chain") or []
        is_supplier = ("sundry creditors" in chain) if chain else ("receipt" not in (data.get("voucher_type") or "").lower())
        partner = self._party_for_ledger(party_name) or self._get_or_create_partner(party_name, is_supplier=is_supplier)
        journal = self._find_or_create_bank_journal(other_lines[0].get("ledger"))
        vch_num = data.get("voucher_number")
        memo_parts = [data.get("reference") or vch_num]
        if data.get("cheque_no"):
            memo_parts.append(f"Chq: {data['cheque_no']}")
        vals = {
            "payment_type": pay_type,
            "partner_type": "supplier" if is_supplier else "customer",
            "partner_id": partner.id if partner else False,
            "amount": abs(party_amount),
            "date": data.get("date"),
            "memo": " · ".join(p for p in memo_parts if p),
            "journal_id": journal.id if journal else False,
            "company_id": self.company.id,
        }

        self._retire_other_model("account.payment")
        rec = self._mapped("account.payment")
        if not rec and data.get("date"):
            candidates = Payment.search([
                ("payment_type", "=", pay_type), ("company_id", "=", self.company.id),
                ("date", "=", data.get("date")), ("partner_id", "=", partner.id if partner else False),
                ("journal_id", "=", journal.id if journal else False), ("state", "!=", "cancel"),
            ]).filtered(lambda p: self.company.currency_id.compare_amounts(p.amount, abs(party_amount)) == 0
                        and not self._is_mapped_elsewhere(p, self.DOCUMENT_ENTITIES)
                        and (p.memo or "").split(" · ")[0] in (data.get("reference"), vch_num))
            rec = candidates if len(candidates) == 1 else Payment

        if data.get("is_cancelled") or data.get("is_deleted"):
            if rec:
                self._cancel_record(rec)
                return rec
            return False

        was_posted = False
        if rec:
            if rec.state != "draft":
                was_posted = rec.state not in ("cancel",)
                rec.action_draft()
            rec.write(vals)
        else:
            rec = Payment.create(vals)

        if rec.state == "draft" and (was_posted or self.instance.auto_post):
            rec.action_post()
            bill_allocs = [b for le in party_lines for b in (le.get("bill_allocations") or [])]
            if bill_allocs:
                self._reconcile_payment_with_allocations(rec, bill_allocs)
        return rec

    def _upsert_journal_voucher(self, data):
        """Journal / Contra / non-standard Receipt & Payment as a balanced entry.

        Each Tally ledger line keeps its own account and, for party ledgers, the
        partner. A rounding difference (should never happen for a valid Tally
        voucher) is parked on a visible suspense account rather than dropped.
        """
        Move = self.env["account.move"]
        vch_num = data.get("voucher_number")
        date_str = data.get("date")
        vtype = (data.get("voucher_type") or "").lower()
        lines = []
        for le in data.get("ledger_entries") or []:
            amt = float(le.get("amount") or 0.0)
            if not amt:
                continue
            account, partner = self._line_target(le.get("ledger"), is_supplier="payment" in vtype)
            lines.append((0, 0, {
                "name": le.get("ledger") or "Journal Entry",
                "account_id": account.id if account else False,
                "partner_id": partner.id if partner else False,
                # Tally: debit = negative amount.
                "debit": abs(amt) if amt < 0 else 0.0,
                "credit": amt if amt > 0 else 0.0,
            }))

        total_debit = sum(line[2]["debit"] for line in lines)
        total_credit = sum(line[2]["credit"] for line in lines)
        diff = self.company.currency_id.round(total_debit - total_credit)
        if diff:
            rounding_account = self._get_or_create_account("Rounding & Suspense Difference", default_type="expense")
            lines.append((0, 0, {
                "name": _("Rounding / Balance Adjustment"),
                "account_id": rounding_account.id,
                "debit": abs(diff) if diff < 0 else 0.0,
                "credit": diff if diff > 0 else 0.0,
            }))

        journal = self._get_or_create_journal("general")
        ref = " / ".join(dict.fromkeys(r for r in (vch_num, data.get("reference")) if r))
        vals = {
            "move_type": "entry",
            "date": date_str,
            "ref": ref or False,
            "narration": f"<p>{data['narration']}</p>" if data.get("narration") else False,
            "journal_id": journal.id if journal else False,
            "company_id": self.company.id,
        }

        self._retire_other_model("account.move")
        rec = self._mapped("account.move")
        if not rec and ref and date_str:
            candidates = Move.search([
                ("move_type", "=", "entry"), ("company_id", "=", self.company.id),
                ("date", "=", date_str), ("ref", "=", ref), ("state", "!=", "cancel"),
            ]).filtered(lambda m: not self._is_mapped_elsewhere(m, self.DOCUMENT_ENTITIES | {"opening_balance"})
                        and self.company.currency_id.compare_amounts(
                            sum(m.line_ids.mapped("debit")), total_debit) == 0)
            rec = candidates if len(candidates) == 1 else Move

        if data.get("is_cancelled") or data.get("is_deleted"):
            if rec:
                self._cancel_record(rec)
                return rec
            return False
        if not lines:
            return False

        counterparts, was_posted = None, False
        if rec:
            if rec.state == "cancel":
                rec.button_draft()
            elif rec.state == "posted":
                was_posted = True
                counterparts = self._reopen_move(rec)
            rec.line_ids.unlink()
            vals["line_ids"] = lines
            rec.write(vals)
        else:
            vals["line_ids"] = lines
            rec = Move.create(vals)
        self._repost(rec, counterparts, force=was_posted)
        return rec

    def _upsert_contra_voucher(self, data):
        """Upsert account.move (contra entry) between Cash and Bank."""
        return self._upsert_journal_voucher(data)

    def _upsert_opening_balance(self, data):
        """Create or update a balanced opening entry for one Tally ledger."""
        amount = float(data.get("opening_balance") or 0.0)
        name = data.get("name") or data.get("ledger")
        if not name:
            return False
        chain = data.get("group_chain") or []
        parent = (data.get("parent") or "").lower()
        is_party = any(g in ("sundry debtors", "sundry creditors") for g in chain) if chain else (
            "debtor" in parent or "creditor" in parent or "customer" in parent
            or "vendor" in parent or "supplier" in parent)
        is_supplier = ("sundry creditors" in chain) if chain else (
            "creditor" in parent or "vendor" in parent or "supplier" in parent)
        partner = False
        if is_party:
            partner = self._party_for_ledger(name) or self._get_or_create_partner(name, is_supplier=is_supplier)
            account = (partner.property_account_payable_id if is_supplier
                       else partner.property_account_receivable_id)
        elif self._is_bank_ledger(name) and chain:
            journal = self._find_or_create_bank_journal(name)
            account = journal.default_account_id if journal and journal.default_account_id else \
                self._account_for_ledger(name, default_type="asset_cash")
        else:
            account = self._account_for_ledger(
                name, default_type=self._map_tally_group_to_account_type(chain or parent))
        counterpart = self._get_or_create_account(
            "Tally Opening Balance Equity", default_type="equity")
        journal = self._get_or_create_journal("general")
        ref = "TALLY-OPEN-%s" % (data.get("guid") or name)
        Move = self.env["account.move"]
        move = self._mapped("account.move") or Move.search([
            ("ref", "=", ref), ("company_id", "=", self.company.id),
            ("move_type", "=", "entry"),
        ], limit=1)
        if not amount:
            # Opening balance cleared in Tally.
            if move and move.state != "cancel":
                self._cancel_record(move)
                return move
            return False
        # Tally: debit = negative.
        debit, credit = (abs(amount), 0.0) if amount < 0 else (0.0, amount)
        lines = [
            (0, 0, {"name": name, "account_id": account.id,
                    "partner_id": partner.id if partner else False,
                    "debit": debit, "credit": credit}),
            (0, 0, {"name": _("Opening balance counterpart"), "account_id": counterpart.id,
                    "debit": credit, "credit": debit}),
        ]
        vals = {
            "move_type": "entry",
            "date": self.instance._opening_balance_date(),
            "ref": ref, "journal_id": journal.id, "company_id": self.company.id,
            "line_ids": lines,
        }
        counterparts, was_posted = None, False
        if move:
            if move.state == "cancel":
                move.button_draft()
            elif move.state == "posted":
                was_posted = True
                counterparts = self._reopen_move(move)
            move.line_ids.unlink()
            move.write(vals)
        else:
            move = Move.create(vals)
        self._repost(move, counterparts, force=was_posted)
        return move

    def _upsert_stock_journal(self, data):
        """Import a Tally Stock Journal as an internal Odoo stock transfer."""
        entries = data.get("inventory_entries") or []
        outgoing = [e for e in entries if float(e.get("qty") or 0.0) < 0]
        incoming = [e for e in entries if float(e.get("qty") or 0.0) > 0]
        if not outgoing or not incoming:
            raise ValueError(_("Stock Journal requires both outward and inward inventory lines."))
        Picking = self.env["stock.picking"]
        ref = (data.get("reference") or data.get("narration") or
               data.get("voucher_number") or data.get("guid"))
        picking = Picking.search([
            ("origin", "=", ref), ("company_id", "=", self.company.id),
            ("picking_type_id.code", "=", "internal"),
        ], limit=1)
        picking_type = self.env["stock.picking.type"].search([
            ("code", "=", "internal"), ("company_id", "in", (False, self.company.id)),
        ], limit=1)
        if not picking_type:
            # A fresh Odoo database may have Inventory installed without a
            # warehouse for the target company.  Creating the warehouse also
            # creates the standard internal-transfer operation type and stock
            # location hierarchy required by the imported Stock Journal.
            Warehouse = self.env["stock.warehouse"]
            warehouse = Warehouse.search([("company_id", "=", self.company.id)], limit=1)
            if not warehouse:
                import re
                base_code = re.sub(r"[^A-Z0-9]", "", (self.company.name or "TLY").upper())[:3] or "TLY"
                code = base_code
                suffix = 1
                while Warehouse.search_count([("code", "=", code)]):
                    suffix += 1
                    code = "%s%s" % (base_code[:max(1, 5 - len(str(suffix)))], suffix)
                warehouse = Warehouse.create({
                    "name": _("%s Warehouse") % self.company.name,
                    "code": code,
                    "company_id": self.company.id,
                })
            picking_type = warehouse.int_type_id or self.env["stock.picking.type"].search([
                ("code", "=", "internal"), ("warehouse_id", "=", warehouse.id),
            ], limit=1)
        if not picking_type:
            raise ValueError(_("Unable to configure an internal transfer operation type."))
        move_commands = []
        for source_line in outgoing:
            product = self._get_or_create_product(source_line.get("item"))
            destination_line = next(
                (e for e in incoming if e.get("item") == source_line.get("item")), incoming[0])
            source = self._upsert_godown({"name": source_line.get("godown") or "Main Location"})
            destination = self._upsert_godown({"name": destination_line.get("godown") or "Main Location"})
            move_vals = {
                "description_picking": source_line.get("item") or ref,
                "product_id": product.id,
                "product_uom_qty": abs(float(source_line.get("qty") or 0.0)),
                move_uom_field(self.env): product.uom_id.id,
                "location_id": source.id,
                "location_dest_id": destination.id,
            }
            # Odoo 18 requires ``stock.move.name``; Odoo 19 removed it in favor
            # of ``description_picking``.
            if "name" in self.env["stock.move"]._fields:
                move_vals["name"] = source_line.get("item") or ref
            move_commands.append((0, 0, move_vals))
        vals = {
            "picking_type_id": picking_type.id,
            "location_id": move_commands[0][2]["location_id"],
            "location_dest_id": move_commands[0][2]["location_dest_id"],
            "origin": ref,
            "scheduled_date": data.get("date") or fields.Datetime.now(),
            "company_id": self.company.id,
            "move_ids": move_commands,
        }
        if not picking:
            picking = Picking.create(vals)
        elif picking.state == "draft":
            picking.move_ids.unlink()
            picking.write(vals)
        if self.instance.auto_post and picking.state not in ("done", "cancel"):
            if picking.state == "draft":
                picking.action_confirm()
            for move in picking.move_ids:
                move.quantity = move.product_uom_qty
                move.picked = True
            picking._action_done()
        return picking

    # =========================================================================
    # HELPER LOOKUPS
    # =========================================================================

    def _map_tally_group_to_account_type(self, tally_group):
        """Resolve an Odoo account_type from a Tally group or group chain.

        ``tally_group`` may be a single group name or the ledger's ancestry
        (nearest first). The nearest group present in ``tally.account.type.map``
        wins, so a custom sub-group such as "Loans to Staff" under "Loans &
        Advances (Asset)" gets the asset type instead of a generic fallback.
        """
        chain = tally_group if isinstance(tally_group, (list, tuple)) else [tally_group or ""]
        Map = self.env["tally.account.type.map"]
        for group in chain:
            rec = Map.search([("tally_group", "=ilike", group)], limit=1)
            if rec:
                return rec.account_type
        for group in chain:
            grp = (group or "").lower()
            if "bank" in grp or "cash" in grp:
                return "asset_cash"
            if "debtor" in grp:
                return "asset_receivable"
            if "creditor" in grp:
                return "liability_payable"
            if "fixed asset" in grp:
                return "asset_fixed"
            if "income" in grp or "sales" in grp:
                return "income"
            if "expense" in grp or "purchase" in grp:
                return "expense"
            if "capital" in grp or "reserve" in grp:
                return "equity"
            if "asset" in grp or "deposit" in grp or "advance" in grp or "stock-in-hand" in grp:
                return "asset_current"
            if "liabilit" in grp or "loan" in grp or "provision" in grp or "duties" in grp:
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
