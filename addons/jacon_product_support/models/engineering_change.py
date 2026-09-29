from odoo import api, fields, models


class EngineeringChange(models.Model):
    _inherit = 'engineering.change'

    # One2many only as the inverse of the 1-1 link (unique on the request side);
    # support_request_id is what the form shows.
    support_request_ids = fields.One2many('product.support.request', 'ec_id')
    support_request_id = fields.Many2one(
        'product.support.request', string='Product Support Request',
        compute='_compute_support_request_id')

    @api.depends('support_request_ids')
    def _compute_support_request_id(self):
        for rec in self:
            rec.support_request_id = rec.support_request_ids[:1]
