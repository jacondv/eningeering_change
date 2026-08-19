from odoo import _, api, fields, models
from odoo.exceptions import AccessDenied, AccessError, UserError, ValidationError

# Fields that stay freely editable regardless of the fill-once-then-lock
# rule below - operational/workflow controls (stage, active, tags, who's
# on the project) are meant to change repeatedly over a project's life,
# unlike one-off data entry fields (PO number, serials, release dates...).
FIELD_LOCK_EXEMPT_FIELDS = frozenset({
    'active', 'stage_id', 'kanban_state', 'kanban_state_label',
    'tag_ids', 'color', 'sequence', 'priority', 'favorite_user_ids',
    'user_id', 'member_ids', 'is_favorite', 'privacy_visibility',
    'is_unlocked', 'task_count', 'open_task_count', 'label_tasks',
    'access_token', 'access_url', 'access_warning',
})


class ProjectProject(models.Model):
    _inherit = 'project.project'

    po_number = fields.Char(string='PO Number')
    po_received_date = fields.Date(string='PO Received')
    iof_release_date = fields.Date(string='IOF Release')
    bom_release_date = fields.Date(string='BOM Release')
    drawing_release_date = fields.Date(string='Drawing Release')
    qc_checksheet_date = fields.Date(string='QC Checksheet')
    photo_taken_date = fields.Date(string='Photo Taken')
    dispatch_date = fields.Date(string='Dispatch Date')
    project_events_note = fields.Text(string='Note')

    machine_serial = fields.Char(string='Machine Serial')
    engine_serial = fields.Char(string='Engine Serial')
    vin_tin = fields.Char(string='VIN/TIN')

    is_unlocked = fields.Boolean(
        string='Unlocked for Editing', compute='_compute_is_unlocked',
        inverse='_inverse_is_unlocked',
        help="Not stored - always recomputed on load, so a project is "
             "always locked again after being saved or the page is "
             "refreshed. New (unsaved) projects are always unlocked. "
             "See the Edit button on the form.")

    def _compute_is_unlocked(self):
        for project in self:
            project.is_unlocked = not project.id

    def _inverse_is_unlocked(self):
        # No-op: this field is intentionally never persisted - see the
        # help text. The client sets it in-memory (via the Edit button)
        # to unlock the form for the current editing session only.
        pass

    @api.constrains('name', 'company_id', 'is_template')
    def _check_name_unique(self):
        for project in self:
            if project.is_template or not project.name:
                continue
            duplicate = self.with_context(active_test=False).search([
                ('id', '!=', project.id),
                ('name', '=ilike', project.name),
                ('company_id', '=', project.company_id.id),
                ('is_template', '=', False),
            ], limit=1)
            if duplicate:
                raise ValidationError(_(
                    "A Project named '%(name)s' already exists. "
                    "Project Name/Job # must be unique.",
                    name=project.name))

    def _check_field_fill_once_access(self, vals):
        """Data-entry fields (PO number, serials, release dates, notes...)
        can only be filled in by the project's own Project Manager
        (`user_id`) while still empty; once a field has a value, it is
        locked for everyone (including that same Project Manager) except
        Administrators. Operational/workflow fields are exempt - see
        FIELD_LOCK_EXEMPT_FIELDS."""
        if self.env.su or self.env.user.has_group('base.group_system'):
            return
        for project in self:
            for field_name in vals:
                if field_name in FIELD_LOCK_EXEMPT_FIELDS:
                    continue
                if field_name not in project._fields:
                    continue
                current_value = project[field_name]
                if isinstance(current_value, models.BaseModel):
                    current_value = current_value.id
                if current_value:
                    raise AccessError(_(
                        "The field '%(field)s' has already been filled in "
                        "and can no longer be changed (only an "
                        "Administrator can).",
                        field=project._fields[field_name].string))
                if self.env.user != project.user_id:
                    raise AccessError(_(
                        "Only this project's Project Manager can fill in "
                        "'%(field)s'.",
                        field=project._fields[field_name].string))

    def write(self, vals):
        self._check_field_fill_once_access(vals)
        return super().write(vals)

    def unlink(self):
        if not self.env.context.get('project_delete_password_confirmed'):
            raise UserError(_(
                "Use the Delete button on the Project form to permanently "
                "delete it - it will ask you to confirm your password first."))
        return super().unlink()

    def action_delete_with_password(self):
        """Opens the shared jacon.delete.password.wizard, which asks for the
        current user's own password - every single time, never cached (see
        the wizard's own docstring for why this isn't the core
        `check_identity` decorator) - before permanently deleting this
        Project. Deletion is otherwise irreversible, unlike Archive, so
        this is intentionally harder to trigger than the plain Action >
        Delete menu (which unlink() above refuses outright).
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Confirm Deletion'),
            'res_model': 'jacon.delete.password.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_res_model': self._name,
                'default_res_id': self.id,
                'default_redirect_action_xmlid': 'project.open_view_project_all',
            },
        }

    def check_edit_password(self, password):
        """Verify `password` against the current user's own login
        credentials. Used by the Edit-lock button on the Project form -
        does not use/require the password of the project's Customer or
        any other party, only the logged-in user's own account."""
        self.ensure_one()
        credential = {'login': self.env.user.login, 'password': password, 'type': 'password'}
        try:
            self.env.user._check_credentials(credential, {'interactive': True})
        except AccessDenied:
            return False
        return True
