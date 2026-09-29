# -*- coding: utf-8 -*-
"""Shared helpers for Odoo -> Tally outbound hooks."""
import hashlib
import logging

_logger = logging.getLogger(__name__)


def target_instances(env, entity, companies=None):
    """Active instances that push ``entity`` to Tally.

    ``companies`` empty means the record is shared between companies (e.g. a
    contact with no company): it belongs in every company's Tally books.
    """
    domain = [("active", "=", True)]
    if companies:
        domain.append(("company_id", "in", companies.ids))
    instances = env["tally.instance"].sudo().search(domain)
    return instances.filtered(lambda inst: any(
        cfg.entity == entity and cfg.enabled and cfg.direction in ("odoo_to_tally", "both")
        for cfg in inst.entity_config_ids))


def tally_name(instance, entity, record, fallback=None):
    """The name Tally uses for an Odoo master: the bound Tally name when the
    record is linked (it may differ from the Odoo name, e.g. in CoA-map mode),
    otherwise the Odoo name."""
    if not record:
        return fallback
    mapping = record.env["tally.mapping"].sudo().for_record(instance, entity, record._name, record.id)
    if mapping.tally_guid and mapping.tally_name:
        return mapping.tally_name
    return getattr(record, "name", None) or fallback


def party_ledger_name(instance, partner, fallback="Cash"):
    partner = partner.commercial_partner_id if partner else partner
    return tally_name(instance, "ledger", partner, fallback=fallback) if partner else fallback


def account_ledger_name(instance, account):
    return tally_name(instance, "account_ledger", account, fallback="Suspense")


def enqueue(instance, entity, record, payload, guid, key=None, tally_name_value=None,
            allow_tally_origin=False, fingerprint=None):
    """Register the push on the identity map and queue it, unless it is an
    identical re-push or a record owned by Tally that policy keeps read-only."""
    env = record.env
    Mapping = env["tally.mapping"].sudo()
    if not Mapping.register_outbound(
            instance, entity, record._name, record.id, payload, guid=guid,
            allow_tally_origin=allow_tally_origin, tally_name=tally_name_value,
            fingerprint=fingerprint):
        return False
    Queue = env["tally.sync.queue"].sudo()
    # One pending delivery per record: a newer payload replaces an unsent one.
    pending = Queue.search([
        ("instance_id", "=", instance.id), ("entity", "=", entity),
        ("odoo_model_name", "=", record._name), ("odoo_res_id", "=", record.id),
        ("state", "=", "pending"),
    ], order="id desc", limit=1)
    key = key or "%s:%s" % (entity, guid)
    if pending:
        pending.write({"payload": payload, "idempotency_key": key})
        return pending
    return Queue.create({
        "instance_id": instance.id,
        "entity": entity,
        "odoo_model_name": record._name,
        "odoo_res_id": record.id,
        "idempotency_key": key,
        "payload": payload,
        "state": "pending",
    })


def godown_name(instance, location):
    """Tally godown for an Odoo location.

    The company's main stock location is Tally's reserved "Main Location" (the
    inbound side maps it the same way); other locations use their full path so
    two warehouses' "Stock" locations never collide in Tally.
    """
    mapping = location.env["tally.mapping"].sudo().for_record(
        instance, "godown", location._name, location.id)
    if mapping.tally_guid and mapping.tally_name:
        return mapping.tally_name
    main = location.env["stock.warehouse"].sudo().search(
        [("company_id", "=", instance.company_id.id)], limit=1).lot_stock_id
    if location == main:
        return "Main Location"
    return location.complete_name or location.name


def document_fingerprint(record):
    """Accounting content of a document (date, partner, account/partner/amount
    per line). Posting, reconciling or re-saving does not change it; editing
    amounts, accounts, partners or the date does."""
    if record._name == "stock.picking":
        data = (str(record.date_done or record.scheduled_date), sorted(
            (m.product_id.id, m.location_id.id, m.location_dest_id.id, round(m.quantity, 4))
            for m in record.move_ids))
    else:
        move = record.move_id if record._name == "account.payment" else record
        data = (str(move.date), move.partner_id.commercial_partner_id.id, sorted(
            (l.account_id.id, l.partner_id.commercial_partner_id.id or 0, round(l.balance, 2))
            for l in move.line_ids if round(l.balance, 2)))
    return hashlib.sha256(repr(data).encode("utf-8")).hexdigest()


def voucher_addressing(instance, entity, record):
    """How to address a document's voucher in Tally.

    * Created by Odoo: re-send with the same REMOTEID (Tally alters/restores the
      exact voucher it stored under that id; type-safe).
    * Typed in Tally: Tally does not store a REMOTEID, so the only handle is date
      + voucher number. Tally matches that pair *across voucher types* (a Journal
      alter hit Sales 1 in testing), so dispatch verifies the pair is unique
      before sending (see ``tally.instance._verify_voucher_address``).
    Returns ``(guid, alter_address_or_None, mapping)``.
    """
    Mapping = record.env["tally.mapping"].sudo()
    mapping = Mapping.for_record(instance, entity, record._name, record.id)
    guid = Mapping.outbound_guid(instance, entity, record._name, record.id)
    if mapping.tally_guid and mapping.last_origin == "tally" and mapping.tally_voucher_number:
        return guid, {"voucher_number": mapping.tally_voucher_number,
                      "date": mapping.tally_voucher_date,
                      "voucher_type": mapping.tally_voucher_type}, mapping
    return guid, None, mapping


def voucher_cancel_message(mapping, voucher_type, narration):
    from ..services import tally_xml_builder
    remote = mapping.remote_id if mapping.last_origin == "odoo" else None
    return tally_xml_builder.build_voucher_cancel_xml(
        mapping.tally_voucher_type or voucher_type, mapping.tally_voucher_number,
        mapping.tally_voucher_date, narration=narration, remote_id=remote)
