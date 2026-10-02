from odoo import fields, models


class ProjectProject(models.Model):
    _inherit = 'project.project'

    is_ps_project = fields.Boolean(
        string='Created for a Product Support Request', copy=False,
        help="Hidden container project holding one Support Request's Actions.")
    support_request_ids = fields.One2many(
        'product.support.request', 'job_id', string='Product Support')

    def _compute_engineering_change_ids(self):
        # Also the ECs linked indirectly through this Job's Support Requests
        # (Request -> ECN No.). Archived ECs are left out, same as the
        # search() the direct link goes through.
        super()._compute_engineering_change_ids()
        for rec in self:
            rec.engineering_change_ids = (
                rec.engineering_change_ids | rec.support_request_ids.ec_id.filtered('active')
            ).sorted('create_date', reverse=True)
