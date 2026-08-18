from odoo import _, api, fields, models
from odoo.addons.base.models.res_users import check_identity
from odoo.exceptions import AccessDenied, UserError, ValidationError


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

    def unlink(self):
        if not self.env.context.get('project_delete_password_confirmed'):
            raise UserError(_(
                "Use the Delete button on the Project form to permanently "
                "delete it - it will ask you to confirm your password first."))
        return super().unlink()

    @check_identity
    def action_delete_with_password(self):
        """Permanently delete this Project. Wrapped in Odoo's standard
        password re-check (`check_identity`): the first call pops up the
        core "Access Control" wizard instead of running this method, and
        only calls back into it once the user's password has been
        confirmed - see `res.users.identitycheck` in the `base` module.
        Deletion is otherwise irreversible, unlike Archive, so this is
        intentionally harder to trigger than the plain Action > Delete menu
        (which unlink() above refuses outright).
        """
        self.with_context(project_delete_password_confirmed=True).unlink()
        # Redirect back to the list instead of ir.actions.act_window_close:
        # this button lives on a full-page form (not a dialog), so closing
        # alone leaves the client trying to reload the now-deleted record.
        return self.env['ir.actions.act_window']._for_xml_id('project.open_view_project_all')

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
