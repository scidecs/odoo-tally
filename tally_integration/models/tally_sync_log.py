# -*- coding: utf-8 -*-
from odoo import api, fields, models
from .constants import ENTITY_SELECTION, DIRECTION_SELECTION


class TallySyncLog(models.Model):
    _name = "tally.sync.log"
    _description = "Tally Sync Log"
    _order = "create_date desc"
    _rec_name = "message"

    instance_id = fields.Many2one(
        "tally.instance", ondelete="cascade", index=True)
    company_id = fields.Many2one(
        related="instance_id.company_id", store=True, index=True)
    direction = fields.Selection(DIRECTION_SELECTION, index=True)
    entity = fields.Selection(ENTITY_SELECTION, index=True)
    status = fields.Selection(
        [("success", "Success"), ("warning", "Warning"), ("error", "Error")],
        default="success", index=True)
    message = fields.Char()
    detail = fields.Text()
    tally_guid = fields.Char()
    odoo_model_name = fields.Char()
    odoo_res_id = fields.Integer()

    @api.model
    def log(self, instance, direction, entity, status, message, detail=None,
            tally_guid=None, odoo_model_name=None, odoo_res_id=None):
        """Convenience creator used by the sync engine and controllers."""
        return self.sudo().create({
            "instance_id": instance.id if instance else False,
            "direction": direction,
            "entity": entity,
            "status": status,
            "message": message,
            "detail": detail,
            "tally_guid": tally_guid,
            "odoo_model_name": odoo_model_name,
            "odoo_res_id": odoo_res_id,
        })
