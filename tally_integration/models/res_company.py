# -*- coding: utf-8 -*-
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    tally_default_source = fields.Selection(
        [("tally", "Tally"), ("odoo", "Odoo")],
        string="Default Source of Truth",
        default="tally",
        help="Which system wins on conflict by default. Tally is the accounting "
             "system, so it is authoritative unless an entity overrides this.",
    )
