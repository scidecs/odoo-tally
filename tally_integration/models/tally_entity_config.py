# -*- coding: utf-8 -*-
from odoo import fields, models
from .constants import ENTITY_SELECTION, SOURCE_OF_TRUTH_SELECTION, DIRECTION_SELECTION


class TallyEntityConfig(models.Model):
    _name = "tally.entity.config"
    _description = "Tally Entity Sync Configuration"
    _order = "sequence, id"

    instance_id = fields.Many2one(
        "tally.instance", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(
        related="instance_id.company_id", store=True, index=True)
    sequence = fields.Integer(default=10)
    entity = fields.Selection(ENTITY_SELECTION, required=True)
    odoo_model_name = fields.Char(string="Odoo Model")
    enabled = fields.Boolean(default=True)
    direction = fields.Selection(
        DIRECTION_SELECTION, default="tally_to_odoo", required=True)
    source_of_truth = fields.Selection(
        SOURCE_OF_TRUTH_SELECTION, default="tally", required=True,
        help="Winner on conflict for this entity. Defaults to Tally.")
    last_alterid = fields.Integer(
        string="Last Synced AlterID", readonly=True,
        help="Delta watermark for Tally → Odoo polling.")
    last_sync = fields.Datetime(readonly=True)

    _sql_constraints = [
        ("entity_instance_uniq", "unique(instance_id, entity)",
         "Only one configuration per entity per instance."),
    ]
