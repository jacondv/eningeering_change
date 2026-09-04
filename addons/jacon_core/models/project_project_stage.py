from odoo import fields, models


class ProjectProjectStage(models.Model):
    _inherit = 'project.project.stage'

    is_archival_stage = fields.Boolean(
        default=False,
        help="Cancelled/On-Hold/EOL - a Project moved into one of these is "
             "archived automatically (see ProjectProject.write) and dropped "
             "out of the normal Stage progression: excluded from the "
             "clickable statusbar and from the Kanban board's own stage "
             "columns (see ProjectProject._read_group_expand_non_archival_stages), "
             "reachable only via the Engineering Head buttons on the "
             "Project form, after unlocking it for editing.")
