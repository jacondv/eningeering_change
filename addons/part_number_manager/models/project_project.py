from odoo import models


class ProjectProject(models.Model):
    """Extends project.project purely to cascade a move to the "Done" stage
    onto the Part Numbers attached to it via `job_number`: a part still
    sitting in Draft has no reason to stay there once its job is done.
    """
    _inherit = 'project.project'

    def write(self, vals):
        # Read this before calling super(): some computed/stored fields on
        # this model rewrite `vals` in place via their inverse as part of
        # the base write(), so anything read from it afterwards can no
        # longer be trusted.
        new_stage_id = vals.get('stage_id')
        result = super().write(vals)
        if new_stage_id and self.env['project.project.stage'].browse(new_stage_id).name == 'Done':
            self.env['part_number_manager.part_number'].search([
                ('job_number', 'in', self.ids),
                ('state', '=', 'draft'),
                ('part_number', '!=', False),
            ]).write({'state': 'active'})
        return result
