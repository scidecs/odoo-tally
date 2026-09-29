# -*- coding: utf-8 -*-
"""Outbound event hooks on res.partner for syncing parties to Tally.

Non-invasive by design: guarded by a context flag (so the inbound sync engine
never triggers a loop), fully wrapped in try/except (so a Tally-side error can
never break partner creation for other modules), and a no-op unless an active
instance has the 'ledger' entity enabled outbound.
"""
import logging
from odoo import api, models

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    _inherit = "res.partner"
    TALLY_FIELDS = {"name", "vat", "street", "street2", "city", "zip", "state_id", "country_id", "email", "phone", "mobile", "credit_limit", "parent_id", "is_company"}

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if not self.env.context.get("tally_no_sync"):
            for rec in records:
                rec._enqueue_tally_party()
        return records

    def write(self, vals):
        res = super().write(vals)
        if not self.env.context.get("tally_no_sync") and self.TALLY_FIELDS.intersection(vals):
            for rec in self:
                rec._enqueue_tally_party()
        return res

    def _enqueue_tally_party(self):
        self.ensure_one()
        try:
            # Tally has one ledger per business: individual contacts of a
            # company roll up into their commercial entity.
            if not self.name or self.parent_id:
                return
            from ..services import tally_xml_builder
            from .tally_outbound import enqueue, target_instances
            Mapping = self.env["tally.mapping"].sudo()
            for instance in target_instances(self.env, "ledger", self.company_id):
                guid = Mapping.outbound_guid(instance, "ledger", self._name, self.id)
                old_name = Mapping.outbound_address(instance, "ledger", self._name, self.id).get("name")
                # Keep an existing ledger in the group Tally has it in (possibly a
                # custom sub-group); ranks change as documents are posted and must
                # not move the ledger between Debtors and Creditors.
                known = instance._get_ledger_index().get((old_name or self.name).strip().lower(), {})
                parent_group = known.get("parent") or (
                    "Sundry Creditors" if self.supplier_rank > self.customer_rank else "Sundry Debtors")
                vat = (self.vat or "").strip()
                msg_xml = tally_xml_builder.build_party_ledger_xml(
                    name=self.name,
                    parent=parent_group,
                    gstin=vat or None,
                    pan=vat[2:12] if len(vat) == 15 else None,
                    address_lines=[self.street, self.street2, self.city],
                    state_name=self.state_id.name if self.state_id else None,
                    country_name=self.country_id.name if self.country_id else "India",
                    pincode=self.zip,
                    email=self.email,
                    phone=self.phone or getattr(self, "mobile", None),
                    credit_limit=getattr(self, "credit_limit", 0.0),
                    guid=guid,
                    old_name=old_name,
                )
                envelope_xml = tally_xml_builder.wrap_import_envelope(
                    [msg_xml], company_name=instance.tally_company)
                enqueue(instance, "ledger", self, envelope_xml, guid,
                        tally_name_value=self.name, allow_tally_origin=True)
        except Exception as e:
            _logger.warning("Tally party enqueue skipped for partner %s: %s", self.id, e)
