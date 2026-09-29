from odoo import api, fields, models


class ProjectTask(models.Model):
    _inherit = 'project.task'

    support_request_id = fields.Many2one(
        'product.support.request', string='Support Request', ondelete='cascade', index=True)

    @api.model_create_multi
    def create(self, vals_list):
        # A Support Request's actions always live in its own container project,
        # whatever project the creating context would otherwise default to.
        Request = self.env['product.support.request']
        for vals in vals_list:
            if vals.get('support_request_id'):
                project = Request.browse(vals['support_request_id']).project_id
                if project:
                    vals['project_id'] = project.id
        return super().create(vals_list)
