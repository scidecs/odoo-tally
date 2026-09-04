# -*- coding: utf-8 -*-
from odoo import _, fields, models


class TallyDiscoveredCompany(models.Model):
    """A Tally company file the on-prem agent has reported as available.

    Lets an administrator map each Tally company to an Odoo company and create
    the paired ``tally.instance`` in one step — the multi-company onboarding entry.
    """
    _name = "tally.discovered.company"
    _description = "Discovered Tally Company"
    _order = "name"

    name = fields.Char(string="Tally Company", required=True, index=True)
    reporter_instance_id = fields.Many2one(
        "tally.instance", string="Reported By", ondelete="cascade", index=True)
    company_id = fields.Many2one(
        related="reporter_instance_id.company_id", store=True, index=True)
    odoo_company_id = fields.Many2one("res.company", string="Map to Odoo Company")
    instance_id = fields.Many2one("tally.instance", string="Paired Instance", readonly=True)
    state = fields.Selection(
        [("new", "New"), ("mapped", "Mapped"), ("ignored", "Ignored")],
        default="new", index=True)
    last_seen = fields.Datetime(readonly=True)

    _name_uniq = models.Constraint(
        "UNIQUE(reporter_instance_id, name)",
        "This Tally company is already listed for this reporting instance.",
    )

    def action_create_instance(self):
        """Create (or link) a tally.instance for this Tally company."""
        Instance = self.env["tally.instance"]
        for rec in self:
            if rec.instance_id:
                continue
            company = rec.odoo_company_id or self.env.company
            instance = Instance.create({
                "name": rec.name,
                "company_id": company.id,
                "tally_company": rec.name,
            })
            instance.action_load_default_entities()
            rec.write({"instance_id": instance.id, "state": "mapped"})
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Instance created"),
                "message": _("A Tally instance was created and seeded with default entities."),
                "type": "success",
            },
        }

    def action_ignore(self):
        self.write({"state": "ignored"})
        return True
