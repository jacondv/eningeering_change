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
            # A sub-task belongs to its parent's request, wherever it's created from.
            parent = self.browse(vals.get('parent_id', self.env.context.get('default_parent_id')))
            request_id = vals.get('support_request_id') or parent.support_request_id.id
            if request_id:
                vals['support_request_id'] = request_id
                project = Request.browse(request_id).project_id
                if project:
                    vals['project_id'] = project.id
        return super().create(vals_list)
