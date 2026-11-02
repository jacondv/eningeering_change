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
    hierarchy_sort_key = fields.Char(
        string='Hierarchy Sort Key', compute='_compute_hierarchy_sort_key',
        store=True, recursive=True, index=True,
        help="Sorting by this lists every task right under its parent, "
             "siblings in creation order. The ids along the path from the "
             "top-level task are zero-padded, as parent_path can't be used "
             "for this: under an en_US collation it sorts 1461/ between "
             "146/ and 146/159/.")

    @api.depends('parent_id', 'parent_id.hierarchy_depth')
    def _compute_hierarchy_depth(self):
        for task in self:
            task.hierarchy_depth = task.parent_id.hierarchy_depth + 1 if task.parent_id else 0

    @api.depends('parent_id', 'parent_id.hierarchy_sort_key')
    def _compute_hierarchy_sort_key(self):
        for task in self:
            own_key = f'{task._origin.id or 0:010d}'
            task.hierarchy_sort_key = (
                f'{task.parent_id.hierarchy_sort_key}/{own_key}' if task.parent_id else own_key
            )
