# -*- coding: utf-8 -*-
from odoo import models


class ResConfigSettings(models.TransientModel):
    """Reserved for future global settings. Company-level source-of-truth is
    configured on the company form (see res_company + res_company view inherit)."""
    _inherit = "res.config.settings"
