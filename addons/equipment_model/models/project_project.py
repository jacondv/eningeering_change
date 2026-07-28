from odoo import fields, models


class ProjectProject(models.Model):
    """A Project (Job Number) is a concrete customer order - one production
    copy of an Equipment Model."""
    _inherit = 'project.project'

    model_id = fields.Many2one('equipment.model', string='Model')
