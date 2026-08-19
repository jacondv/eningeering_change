from odoo import _, fields, models
from odoo.exceptions import AccessError


class ProjectProject(models.Model):
    _inherit = 'project.project'

    is_ec_project = fields.Boolean(
        string='Created for an Engineering Change', copy=False,
        help="True for a project auto-created to hold a single Engineering "
             "Change request's Actions/Tasks (see "
             "EngineeringChange._link_ec_project). Hidden from the main "
             "Projects list - see the action inherits in "
             "project_project_views.xml - but still shown normally in Tasks.")

    def write(self, vals):
        if not self.env.su:
            is_admin = self.env.user.has_group('base.group_system')
            is_head_office = self.env.user.has_group('engineering_change.group_ec_head_office')
            if 'stage_id' in vals and not (is_admin or is_head_office):
                raise AccessError(_(
                    "Only the Engineering Head or an Administrator can "
                    "change a Project's Stage."))
            if is_head_office and not is_admin:
                # Reaches every project (see project_project_rules.xml),
                # not just their own - but only to change Stage; editing
                # anything else on someone else's project still requires
                # actually being that project's own Project Manager.
                other_fields = set(vals) - {'stage_id'}
                if other_fields and any(p.user_id != self.env.user for p in self):
                    raise AccessError(_(
                        "As Engineering Head you can only change a "
                        "Project's Stage, unless it's your own project."))
        return super().write(vals)
