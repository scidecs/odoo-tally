# -*- coding: utf-8 -*-
from odoo import api, fields, models
from .constants import ACCOUNT_TYPE_SELECTION


class TallyAccountTypeMap(models.Model):
    """Maps a Tally group (primary or reserved sub-group) to an Odoo account_type.

    Used by the CoA transform when importing Tally ledgers/groups as
    ``account.account`` records. Editable in native UI; seeded with sensible
    defaults for Tally's reserved groups.
    """
    _name = "tally.account.type.map"
    _description = "Tally Group → Odoo Account Type"
    _order = "sequence, tally_group"

    sequence = fields.Integer(default=10)
    tally_group = fields.Char(
        string="Tally Group", required=True,
        help="Tally primary group or reserved sub-group name, e.g. 'Sundry Debtors'.")
    account_type = fields.Selection(
        ACCOUNT_TYPE_SELECTION, string="Odoo Account Type", required=True)
    note = fields.Char()

    _sql_constraints = [
        ("tally_group_uniq", "unique(tally_group)",
         "A mapping for this Tally group already exists."),
    ]

    @api.model
    def resolve(self, tally_group):
        """Return the Odoo account_type for a Tally group name (case-insensitive)."""
        if not tally_group:
            return "asset_current"
        rec = self.search([("tally_group", "=ilike", tally_group)], limit=1)
        return rec.account_type if rec else "asset_current"
