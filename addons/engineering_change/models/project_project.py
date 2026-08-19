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
