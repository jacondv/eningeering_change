from odoo import _, api, fields, models
from odoo.exceptions import AccessDenied, AccessError, UserError, ValidationError


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

    def write(self, vals):
        if 'stage_id' in vals and not self.env.su:
            is_admin = self.env.user.has_group('base.group_system')
            is_head_office = self.env.user.has_group('jacon_core.group_ec_head_office')
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
