from odoo import fields, models


class ProjectUpdate(models.Model):
    _inherit = 'project.update'

    # Full replacement (not selection_add) - mirrors project.project's
    # last_update_status (project_project.py), which is itself just a
    # compute reading `last_update_id.status`, so both Selections must
    # carry exactly the same values or writing one of them would
    # immediately get overwritten back to a stale value on the next
    # recompute. Drops core's on_track/at_risk/off_track/done in favor of
    # 'in_progress'; adds 'cancelled'/'eol'.
    status = fields.Selection(selection=[
        ('in_progress', 'In Progress'),
        ('on_hold', 'On Hold'),
        ('cancelled', 'Cancelled'),
        ('eol', 'EOL'),
    ], required=True, tracking=True, export_string_translation=False)
