from odoo import fields, models


class ProjectProject(models.Model):
    _inherit = 'project.project'

    is_ec_project = fields.Boolean(
        string='Created for an Engineering Change', copy=False,
        help="True for a project auto-created to hold a single Engineering "
             "Change request's Actions/Tasks (see "
             "EngineeringChange._link_ec_project). Hidden from the main "
             "Projects list - see the action inherits in "
             "project_project_views.xml - but still shown normally in Tasks.")
    engineering_change_ids = fields.Many2many(
        'engineering.change', compute='_compute_engineering_change_ids',
        string='Engineering Changes', groups='engineering_change.group_ec_user',
        help="DCR/ECN requests related to this Job Number - those whose "
             "Impacted Job Numbers (rolled up from their Actions) include it.")

    def _compute_engineering_change_ids(self):
        Change = self.env['engineering.change']
        # affected_project_ids is a stored rollup - make sure any pending
        # recompute (e.g. an Action edited earlier in this same transaction)
        # lands before searching on it.
        Change.flush_model(['affected_project_ids'])
        for rec in self:
            # _origin: in an onchange/new-record context rec.id is a NewId.
            project_id = rec._origin.id
            rec.engineering_change_ids = Change.search(
                [('affected_project_ids', 'in', project_id)]) if project_id else Change
