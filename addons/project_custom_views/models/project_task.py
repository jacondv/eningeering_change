from odoo import api, fields, models


class ProjectTask(models.Model):
    _inherit = 'project.task'
    _parent_store = True

    parent_path = fields.Char(index=True)
    hierarchy_depth = fields.Integer(
        string='Hierarchy Depth', compute='_compute_hierarchy_depth',
        store=True, recursive=True,
        help="Number of ancestor tasks above this one (0 for a top-level "
             "task). Used to indent sub-tasks under their parent in the "
             "Tasks list view.")

    @api.depends('parent_id', 'parent_id.hierarchy_depth')
    def _compute_hierarchy_depth(self):
        for task in self:
            task.hierarchy_depth = task.parent_id.hierarchy_depth + 1 if task.parent_id else 0
