# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    tally_default_source = fields.Selection(
        related="company_id.tally_default_source",
        readonly=False,
        string="Default Source of Truth",
        help="Which system wins on conflict by default. Tally is the accounting "
             "system, so it is authoritative unless an entity overrides this.",
    )
