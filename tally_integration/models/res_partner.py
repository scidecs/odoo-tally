# -*- coding: utf-8 -*-
"""Outbound event hooks on res.partner for syncing parties to Tally."""
import logging
from odoo import api, fields, models
from ..services import tally_xml_builder

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    _inherit = "res.partner"

    @api.model_create_multi
    def create(self, vals_list):
        records = super(ResPartner, self).create(vals_list)
        for rec in records:
            rec._enqueue_tally_party()
        return records

    def write(self, vals):
        res = super(ResPartner, self).write(vals)
        for rec in self:
            rec._enqueue_tally_party()
        return res

    def _enqueue_tally_party(self):
        """Enqueue partner master into Tally sync queue."""
        self.ensure_one()
        # Avoid syncing internal contacts without name or company
        if not self.name:
            return

        company = self.company_id or self.env.company
        instance = self.env["tally.instance"].search([
            ("company_id", "=", company.id),
            ("active", "=", True),
        ], limit=1)
        if not instance:
            return

        cfg = instance.entity_config_ids.filtered(lambda c: c.entity == "ledger" and c.enabled)
        if not cfg or cfg.direction not in ("odoo_to_tally", "both"):
            return

        parent_group = "Sundry Creditors" if self.supplier_rank > 0 else "Sundry Debtors"
        address_lines = [self.street, self.street2]

        msg_xml = tally_xml_builder.build_party_ledger_xml(
            name=self.name,
            parent=parent_group,
            gstin=self.vat,
            pan=self.vat[2:12] if (self.vat and len(self.vat) == 15) else None,
            address_lines=address_lines,
            state_name=self.state_id.name if self.state_id else None,
            country_name=self.country_id.name if self.country_id else "India",
            pincode=self.zip,
            email=self.email,
            phone=self.phone or self.mobile,
            credit_limit=self.credit_limit if hasattr(self, "credit_limit") else 0.0,
        )
        envelope_xml = tally_xml_builder.wrap_import_envelope([msg_xml], company_name=instance.tally_company)

        idempotency_key = f"odoo_partner_{self.id}_{self.write_date.strftime('%Y%m%d%H%M%S') if self.write_date else ''}"
        self.env["tally.sync.queue"].create({
            "instance_id": instance.id,
            "entity": "ledger",
            "odoo_model_name": self._name,
            "odoo_res_id": self.id,
            "idempotency_key": idempotency_key,
            "payload": envelope_xml,
            "state": "pending",
        })
