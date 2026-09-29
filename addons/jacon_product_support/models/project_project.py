from odoo import fields, models


class ProjectProject(models.Model):
    _inherit = 'project.project'

    is_ps_project = fields.Boolean(
        string='Created for a Product Support Request', copy=False,
        help="Hidden container project holding one Support Request's Actions.")
    support_request_ids = fields.One2many(
        'product.support.request', 'job_id', string='Product Support')
