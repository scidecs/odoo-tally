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

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if not self.env.context.get("tally_no_sync"):
            for rec in records:
                rec._enqueue_tally_party()
        return records

    def write(self, vals):
        res = super().write(vals)
        if not self.env.context.get("tally_no_sync"):
            for rec in self:
                rec._enqueue_tally_party()
        return res

    def _enqueue_tally_party(self):
        self.ensure_one()
        try:
            if not self.name:
                return
            company = self.company_id or self.env.company
            instance = self.env["tally.instance"].search(
                [("company_id", "=", company.id), ("active", "=", True)], limit=1)
            if not instance:
                return
            cfg = instance.entity_config_ids.filtered(
                lambda c: c.entity == "ledger" and c.enabled)
            if not cfg or cfg.direction not in ("odoo_to_tally", "both"):
                return

            from ..services import tally_xml_builder
            guid = self.env["tally.mapping"].outbound_guid(
                instance, "ledger", self._name, self.id)
            parent_group = "Sundry Creditors" if self.supplier_rank > 0 else "Sundry Debtors"
            msg_xml = tally_xml_builder.build_party_ledger_xml(
                name=self.name,
                parent=parent_group,
                gstin=self.vat,
                pan=self.vat[2:12] if (self.vat and len(self.vat) == 15) else None,
                address_lines=[self.street, self.street2],
                state_name=self.state_id.name if self.state_id else None,
                country_name=self.country_id.name if self.country_id else "India",
                pincode=self.zip,
                email=self.email,
                phone=self.phone or getattr(self, "mobile", None),
                credit_limit=getattr(self, "credit_limit", 0.0),
                guid=guid,
            )
            envelope_xml = tally_xml_builder.wrap_import_envelope(
                [msg_xml], company_name=instance.tally_company)

            should_enqueue = self.env["tally.mapping"].register_outbound(
                instance=instance,
                entity="ledger",
                model_name=self._name,
                res_id=self.id,
                payload_xml=envelope_xml,
                guid=guid,
                allow_tally_origin=True,
            )
            if not should_enqueue:
                return

            self.env["tally.sync.queue"].create({
                "instance_id": instance.id,
                "entity": "ledger",
                "odoo_model_name": self._name,
                "odoo_res_id": self.id,
                "idempotency_key": "odoo_partner_%s_%s" % (
                    self.id, self.write_date and self.write_date.strftime("%Y%m%d%H%M%S") or ""),
                "payload": envelope_xml,
                "state": "pending",
            })
        except Exception as e:
            _logger.warning("Tally party enqueue skipped for partner %s: %s", self.id, e)
