from odoo import _, api, fields, models
from odoo.exceptions import AccessDenied, AccessError, UserError, ValidationError

# project.update's own STATUS_COLOR dict (also imported and reused as-is by
# project.project._compute_last_update_color) has no extension hook - it's a
# plain Python dict keyed by every valid `status`/`last_update_status` value,
# looked up directly (KeyError on a missing key), not a field one can extend
# via selection_add. Mutating it in place at import time is the standard
# pragmatic way to add colors for the 'cancelled'/'eol' values added below,
# matching the same values added to project.update.status in
# project_update.py. See static/src/project_status/project_status_colors_patch.js
# for the client-side equivalent (the widget keeps its own separate copy of
# this same mapping for rendering not-yet-saved dropdown options).
from odoo.addons.project.models.project_update import STATUS_COLOR
STATUS_COLOR.update({
    'cancelled': 1,  # red (standard Kanban tag color, index 1)
    'eol': 5,  # purple (standard Kanban tag color, index 5)
})

# Which last_update_status values mean "this project is done for" - set on
# a project, they both archive it (see write() below) and are only
# reachable through the dedicated, Manager-gated widget on the form (see
# edit_project_inherit_last_update_status in views/project_project_views.xml).
ARCHIVAL_UPDATE_STATUSES = {'on_hold', 'cancelled', 'eol'}

STATUS_COLOR['in_progress'] = 20  # green - matches core's old 'on_track' color


class ProjectProject(models.Model):
    _inherit = 'project.project'

    # Full replacement (not selection_add) - deliberately drops core's own
    # on_track/at_risk/off_track/done/to_define options entirely, leaving
    # only the 4 values Jacon actually uses. 'on_hold' already existed in
    # core; 'cancelled'/'eol' are new (see ARCHIVAL_UPDATE_STATUSES above);
    # 'in_progress' replaces core's 'to_define' as the default/no-update-yet
    # state, since a normal running project isn't really "undefined".
    last_update_status = fields.Selection(selection=[
        ('in_progress', 'In Progress'),
        ('on_hold', 'On Hold'),
        ('cancelled', 'Cancelled'),
        ('eol', 'EOL'),
    ], default='in_progress', compute='_compute_last_update_status', store=True,
        readonly=False, required=True, export_string_translation=False)
    # UX hint for the view (readonly condition) - see
    # edit_project_inherit_last_update_status in project_project_views.xml.
    # The write() guard above is the actual enforcement; this just lets the
    # form grey the field out accordingly instead of letting a non-manager
    # interact with it only to have the save rejected.
    can_change_last_update_status = fields.Boolean(compute='_compute_can_change_last_update_status')

    @api.depends('last_update_id.status')
    def _compute_last_update_status(self):
        # Same as core's version, except the no-update-yet fallback is
        # 'in_progress' instead of core's 'to_define' - see the field
        # definition above for why.
        for project in self:
            project.last_update_status = project.last_update_id.status or 'in_progress'

    def _compute_can_change_last_update_status(self):
        is_admin = self.env.user.has_group('base.group_system')
        is_head_office = self.env.user.has_group('jacon_core.group_head_office')
        for project in self:
            project.can_change_last_update_status = is_admin or is_head_office

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

    def write(self, vals):
        if 'stage_id' in vals and not self.env.su:
            is_admin = self.env.user.has_group('base.group_system')
            is_head_office = self.env.user.has_group('jacon_core.group_head_office')
            if not (is_admin or is_head_office):
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
        if 'last_update_status' in vals and not self.env.su:
            # Same role gate as Stage above, not the field's own base ACL
            # (any project.group_project_user can write last_update_status
            # by default in core Odoo) - deliberately mirrors the Stage
            # check since this is exactly as consequential (see the
            # auto-archive below) and should require the same role.
            is_admin = self.env.user.has_group('base.group_system')
            is_head_office = self.env.user.has_group('jacon_core.group_head_office')
            if not (is_admin or is_head_office):
                raise AccessError(_(
                    "Only the Engineering Head or an Administrator can "
                    "change a Project's Status."))
        if vals.get('last_update_status') in ARCHIVAL_UPDATE_STATUSES and 'active' not in vals:
            # Checked here, before super().write() - core's own write()
            # (further down the override chain) pops 'last_update_status'
            # out of vals once it's turned it into a project.update record,
            # but 'active' rides along in the same call either way, so this
            # still lands as one atomic write. 'active' not already in
            # vals: don't fight a caller deliberately setting both at once
            # (e.g. a future Reopen-style flow reactivating a project while
            # also clearing its status).
            vals = dict(vals, active=False)
        elif vals.get('last_update_status') == 'in_progress' and 'active' not in vals:
            # Symmetric to the archive above - moving back to In Progress
            # (e.g. resuming an On-Hold project) un-archives it.
            vals = dict(vals, active=True)
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
