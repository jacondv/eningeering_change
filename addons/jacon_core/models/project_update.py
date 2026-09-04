from odoo import fields, models


class ProjectUpdate(models.Model):
    _inherit = 'project.update'

    # Mirrors project.project.last_update_status (project_project.py) - that
    # field is itself just a compute reading `last_update_id.status`, so
    # both Selections must carry the same added values or writing one of
    # them would immediately get overwritten back to a stale value on the
    # next recompute. ondelete='cascade': unlike last_update_status
    # (which falls back to its own default, 'to_define'), this field has no
    # default and is required=True - a fallback status wouldn't have a
    # real place to fall back to, so if this module is ever uninstalled,
    # historical updates logged with these statuses are removed instead.
    status = fields.Selection(selection_add=[
        ('cancelled', 'Cancelled'),
        ('eol', 'EOL'),
    ], ondelete={'cancelled': 'cascade', 'eol': 'cascade'})
