import io
import zipfile

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from .qc_checksheet import GROUP_APPROVER
from .qc_checksheet_change import RUNNING_CHANGE_EXCLUDED_STATES
from .qc_checksheet_print import safe_file_name

GROUP_USER = 'qc_checksheet.group_qc_user'
JOB_REPORT_NAME = 'qc_checksheet.report_qc_job_checksheet_document'


class QcJobChecksheet(models.Model):
    """The Revision of its Model's check sheet that a Job is checked against.

    Created the first time the Job prints a sheet of that Type, pinning the
    Model's Released Revision of that moment. A later Revision of the Model
    doesn't touch it: the Job keeps printing the Revision it started with
    until an Approver approves a request, with a reason, to move it to another.

    Only check_date is written directly; the pin itself only changes through
    _pin(), job_pin() (first pinning, a Revision of the user's choice) and
    _apply_revision() (an approved Revision change request), which run as sudo.
    """
    _name = 'qc.job.checksheet'
    _description = 'Job QC Check Sheet'
    _inherit = ['mail.thread']
    _order = 'job_id desc, type_id'
    _mail_post_access = 'read'

    job_id = fields.Many2one(
        'project.project', string='Job Number', required=True, index=True, ondelete='cascade')
    type_id = fields.Many2one('qc.checksheet.type', string='Type', required=True, ondelete='restrict')
    checksheet_id = fields.Many2one(
        'qc.checksheet', string='Check Sheet Revision', required=True, index=True, ondelete='restrict',
        tracking=True, help="The Revision this Job prints. A newer Revision of the Model doesn't change it.")
    checksheet_type = fields.Selection(related='checksheet_id.checksheet_type', string='Layout')
    model_id = fields.Many2one(related='checksheet_id.model_id', store=True, string='Model')
    reference = fields.Char(related='checksheet_id.reference', string='Number')
    # No sum in a group header: adding up Revision numbers means nothing.
    revision = fields.Integer(related='checksheet_id.revision', string='Rev', aggregator=False)
    root_id = fields.Many2one(related='checksheet_id.root_id', store=True, string='Check Sheet')
    # Stored so the list can filter on it: an On Hold, EOL or Cancelled Job is archived.
    job_status = fields.Selection(related='job_id.last_update_status', store=True, string='Job Status')
    change_ids = fields.One2many('qc.job.checksheet.change', 'job_sheet_id', string='Revision Change Requests')
    pending_change_id = fields.Many2one(
        'qc.job.checksheet.change', string='Pending Change', compute='_compute_pending_change',
        help="The request to change this Job's Revision that waits for approval. Printed on the sheet as a warning.")
    pinned_date = fields.Datetime(string='Pinned On', readonly=True)
    pinned_by_id = fields.Many2one('res.users', string='Pinned By', readonly=True)
    check_date = fields.Date(string='Check Date', tracking=True)

    # Printed on the sheet. Related fields read through sudo, so printing
    # doesn't need access to the Project.
    job_name = fields.Char(related='job_id.name', string='Job')
    machine_serial = fields.Char(related='job_id.machine_serial', string='Machine Serial')
    engine_number = fields.Char(related='job_id.engine_serial', string='Engine Number')
    customer = fields.Char(related='job_id.partner_id.name', string='Customer')
    latest_revision = fields.Integer(
        string='Latest Rev', compute='_compute_latest_revision', aggregator=False,
        help="The Model's current Released Revision of this sheet. Shown next to Rev to spot Jobs on an old one.")
    update_available = fields.Boolean(
        string='Outdated', compute='_compute_update_available', search='_search_update_available',
        help="The Model has a newer Released Revision of this sheet than the one pinned: the pinned one is Superseded.")
    pdf_file_name = fields.Char(
        compute='_compute_pdf_file_name',
        help="<MACHINE SERIAL>-QC-<TYPE NAME> in capitals, or the Job Number when the machine has no Serial yet.")

    _job_type_unique = models.Constraint(
        'UNIQUE(job_id, type_id)',
        'This Job already has a check sheet of this Type.',
    )

    @api.depends('job_name', 'type_id', 'revision')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f'{rec.job_name} · {rec.type_id.name} · Rev {rec.revision}'

    @api.depends('checksheet_id.state', 'checksheet_id.model_id', 'type_id')
    def _compute_latest_revision(self):
        released = self.env['qc.checksheet'].sudo().search([
            ('state', '=', 'released'), ('model_id', 'in', self.job_id.sudo().model_id.ids),
            ('type_id', 'in', self.type_id.ids)])
        current = {(sheet.model_id, sheet.type_id): sheet.revision for sheet in released}
        for rec in self:
            # Nothing Released on the Model: what the Job prints is the latest there is.
            rec.latest_revision = current.get((rec.job_id.sudo().model_id, rec.type_id), rec.revision)

    @api.depends('change_ids.state')
    def _compute_pending_change(self):
        for rec in self:
            rec.pending_change_id = rec.change_ids.filtered(lambda change: change.state == 'pending')[:1]

    @api.depends('checksheet_id.state')
    def _compute_update_available(self):
        # A Revision only becomes Superseded when a newer one is Released.
        for rec in self:
            rec.update_available = rec.checksheet_id.state == 'superseded'

    def _search_update_available(self, operator, value):
        if operator not in ('=', '!='):
            raise UserError(_("Unsupported search on Outdated."))
        outdated = (operator == '=') == bool(value)
        return [('checksheet_id.state', '=' if outdated else '!=', 'superseded')]

    def _file_prefix(self):
        """What starts every file name of this Job's prints: the machine's Serial, or the Job Number without one."""
        self.ensure_one()
        return safe_file_name(self.machine_serial or self.job_name or '')

    @api.depends('machine_serial', 'job_name', 'type_id.name')
    def _compute_pdf_file_name(self):
        for rec in self:
            rec.pdf_file_name = safe_file_name(f'{rec._file_prefix()}-QC-{rec.type_id.name or ""}')

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            raise UserError(_("A Job's check sheet is created when the Job prints it."))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su and vals.keys() - {'check_date'}:
            raise UserError(_("Only the Check Date can be changed. Ask for a change of Revision from the Job's QC page."))
        return super().write(vals)

    # Pinning

    @api.model
    def _check_user(self):
        if not self.env.su and not self.env.user.has_group(GROUP_USER):
            raise AccessError(_("You don't have the access rights for this action."))

    @api.model
    def _current_release(self, model, checksheet_type):
        if not model or not checksheet_type:
            return self.env['qc.checksheet']
        return self.env['qc.checksheet'].search([
            ('model_id', '=', model.id), ('type_id', '=', checksheet_type.id), ('state', '=', 'released'),
        ], limit=1)

    @api.model
    def _pin(self, job, types):
        """The Job's sheet of each Type, pinning the Model's current Released
        Revision for a Type the Job prints for the first time."""
        self._check_user()
        existing = self.search([('job_id', '=', job.id), ('type_id', 'in', types.ids)])
        by_type = {rec.type_id: rec for rec in existing}
        result = self.browse()
        for checksheet_type in types:
            rec = by_type.get(checksheet_type)
            if not rec:
                model = job.sudo().model_id
                if not model:
                    raise UserError(_("Job %s has no Model. Set its Model first.", job.sudo().display_name))
                release = self._current_release(model, checksheet_type)
                if not release:
                    raise UserError(_(
                        "Model %(model)s has no Released %(type)s sheet yet.",
                        model=model.display_name, type=checksheet_type.name))
                rec = self._create_pin(job, checksheet_type, release, _("first print")).sudo(False)
            result |= rec
        return result

    @api.model
    def _create_pin(self, job, checksheet_type, release, note):
        """The one way a Job gets pinned to a Revision, whichever path got it here, so it always leaves the same trace."""
        rec = self.sudo().create({
            'job_id': job.id,
            'type_id': checksheet_type.id,
            'checksheet_id': release.id,
            'pinned_date': fields.Datetime.now(),
            'pinned_by_id': self.env.uid,
        })
        rec.message_post(body=_(
            "Pinned to %(rev)s by %(user)s: %(note)s",
            rev=release.display_name, user=self.env.user.name, note=note.strip()))
        return rec

    @api.model
    def _issued_revisions(self, job, checksheet_type):
        """Every Revision of the Job's Model for this Type that was ever issued: what the Job can be pinned to."""
        return self.env['qc.checksheet'].sudo().search([
            ('model_id', '=', job.sudo().model_id.id), ('type_id', '=', checksheet_type.id),
            ('state', 'in', ('released', 'superseded'))], order='revision desc')

    @api.model
    def job_options(self, job_id, type_id):
        """The Revisions a Job can be pinned, or moved, to, newest first, for the
        Choose/Change Revision dialog. `pinned` marks the one it prints now, if any."""
        job = self.env['project.project'].sudo().browse(job_id).exists()
        checksheet_type = self.env['qc.checksheet.type'].browse(type_id).exists()
        if not job or not checksheet_type:
            raise UserError(_("This Job no longer exists."))
        pinned = self.search([('job_id', '=', job.id), ('type_id', '=', checksheet_type.id)]).checksheet_id
        states = dict(self.env['qc.checksheet']._fields['state'].selection)
        return [{
            'id': sheet.id,
            'revision': sheet.revision,
            'state': sheet.state,
            'state_label': states[sheet.state],
            'reason': sheet.change_reason or '',
            'changes': ', '.join(sheet.change_request_ids.mapped('name')),
            'pinned': sheet == pinned,
            'current': sheet.state == 'released',
        } for sheet in self._issued_revisions(job, checksheet_type)]

    def _check_revision_choice(self, job, checksheet_type, revision_id, reason):
        """The Revision picked, once it is known to be one the Job may take."""
        if not (reason or '').strip():
            raise UserError(_("Enter the reason for choosing this Revision."))
        issued = self._issued_revisions(job, checksheet_type)
        release = issued.browse(revision_id) if revision_id else issued.filtered(lambda s: s.state == 'released')
        if not release:
            raise UserError(_("The Job's Model has no Released sheet of this Type."))
        if release not in issued:
            raise UserError(_("That Revision is not available for this Job. Pick an issued Revision of its Model."))
        return release

    @api.model
    def job_pin(self, job_id, type_id, revision_id, reason):
        """Pin a Job that hasn't printed this sheet yet to the Revision picked
        instead of the Model's current one. First pinning is never approved:
        only moving a pinned Job is."""
        self._check_user()
        job = self.env['project.project'].browse(job_id).exists()
        checksheet_type = self.env['qc.checksheet.type'].browse(type_id).exists()
        if not job or not checksheet_type:
            raise UserError(_("This Job no longer exists."))
        if self.search_count([('job_id', '=', job.id), ('type_id', '=', checksheet_type.id)]):
            raise UserError(_("This Job already printed this sheet. Ask to change its Revision instead."))
        if not job.sudo().model_id:
            raise UserError(_("Job %s has no Model. Set its Model first.", job.sudo().display_name))
        release = self._check_revision_choice(job, checksheet_type, revision_id, reason)
        return self._create_pin(job, checksheet_type, release, reason).id

    def action_request_change(self, reason, revision_id=None):
        """Ask to move this Job to another issued Revision of its Model's sheet:
        by default the current Released one, but any, older ones included. The
        Job keeps its Revision until an Approver approves the request."""
        self.ensure_one()
        self._check_user()
        release = self._check_revision_choice(self.job_id, self.type_id, revision_id, reason)
        if release == self.checksheet_id:
            raise UserError(_("This Job already uses that Revision."))
        if self.env['qc.job.checksheet.change'].search_count([
                ('job_sheet_id', '=', self.id), ('state', '=', 'pending')]):
            raise UserError(_("A change of this sheet is already waiting for approval."))
        request = self.env['qc.job.checksheet.change'].sudo().create({
            'job_sheet_id': self.id,
            'from_checksheet_id': self.checksheet_id.id,
            'to_checksheet_id': release.id,
            'reason': reason.strip(),
            'requested_by_id': self.env.uid,
        })
        request._notify_approvers()
        self.sudo().message_post(body=_(
            "%(user)s asked to change from %(old)s to %(new)s: %(reason)s",
            user=self.env.user.name, old=self.checksheet_id.display_name, new=release.display_name,
            reason=reason.strip()))
        return request.id

    def _apply_revision(self, release, reason, requested_by=None, approved_by=None):
        """Move the pin. Only an approved request gets here (see qc.job.checksheet.change)."""
        self.ensure_one()
        old = self.checksheet_id
        if release == old:
            raise UserError(_("This Job already uses that Revision."))
        if release not in self._issued_revisions(self.job_id, self.type_id):
            raise UserError(_("That Revision is not available for this Job. Pick an issued Revision of its Model."))
        sudo_self = self.sudo()
        sudo_self.write({
            'checksheet_id': release.id,
            'pinned_date': fields.Datetime.now(),
            'pinned_by_id': (approved_by or self.env.user).id,
        })
        sudo_self.message_post(body=_(
            "Updated from %(old)s to %(new)s, asked by %(asker)s, approved by %(user)s: %(reason)s",
            old=old.display_name, new=release.display_name,
            asker=(requested_by or self.env.user).name, user=(approved_by or self.env.user).name,
            reason=reason.strip()))

    # Job QC page (static/src/job)

    @api.model
    def _summary(self, sheet):
        state_labels = dict(sheet._fields['state'].selection)
        return {
            'id': sheet.id,
            'revision': sheet.revision,
            'number': sheet.reference or '',
            'header': sheet.name or '',
            'state': sheet.state,
            'state_label': state_labels[sheet.state],
            'layout': sheet.checksheet_type,
        }

    @api.model
    def job_overview(self, job_id):
        self._check_user()
        # Job details through sudo: seeing a Job's sheets shouldn't need Project access.
        job = self.env['project.project'].sudo().browse(job_id).exists()
        if not job:
            raise UserError(_("This Job no longer exists."))
        pinned = {rec.type_id: rec for rec in self.search([('job_id', '=', job.id)])}
        Type = self.env['qc.checksheet.type']
        Sheet = self.env['qc.checksheet']
        model_sheets = Sheet.search([('model_id', '=', job.model_id.id)]) if job.model_id else Sheet
        # Required Types, plus an optional one the Model has Released; archived
        # Types still show the sheets the Job already printed.
        offered = model_sheets.filtered(lambda s: s.state == 'released').type_id
        types = (Type.search([]) | Type.union(*pinned)).filtered(
            lambda t: t.required or t in pinned or t in offered).sorted(
            lambda t: (not t.required, t.sequence, t.name))
        pending = {change.job_sheet_id: change for change in self.env['qc.job.checksheet.change'].search([
            ('job_sheet_id', 'in', [rec.id for rec in pinned.values()]), ('state', '=', 'pending')])}
        is_approver = self.env.user.has_group(GROUP_APPROVER)
        rows = []
        for checksheet_type in types:
            rec = pinned.get(checksheet_type)
            revisions = model_sheets.filtered(lambda s: s.type_id == checksheet_type).sorted('revision')
            issued = revisions.filtered(lambda s: s.state in ('released', 'superseded'))
            request = pending.get(rec) if rec else None
            current = revisions.filtered(lambda s: s.state == 'released')[:1]
            in_progress = revisions.filtered(lambda s: s.state in ('draft', 'review'))[-1:]
            rows.append({
                'type_id': checksheet_type.id,
                'type_name': checksheet_type.name,
                'required': checksheet_type.required,
                # Plain False, not an empty recordset: that reaches the page as [], which is truthy.
                'pinned': dict(
                    self._summary(rec.checksheet_id),
                    job_sheet_id=rec.id,
                    pinned_date=fields.Datetime.to_string(rec.pinned_date) or '',
                    pinned_by=rec.pinned_by_id.name or '',
                    other_model=rec.model_id != job.model_id,
                ) if rec else False,
                'current': self._summary(current) if current else False,
                'next': self._summary(in_progress) if in_progress else False,
                # Any other issued Revision can be asked for, an older one too, unless one is already waiting.
                'update': bool(rec and not request and (issued - rec.checksheet_id)),
                # Not printed yet: a Revision other than the current one can be chosen at once.
                'choosable': bool(not rec and len(issued) > 1),
                'outdated': bool(rec and rec.update_available),
                'pending': {
                    'id': request.id,
                    'revision': request.to_revision,
                    'requested_by': request.requested_by_id.name or '',
                    'requested_date': fields.Datetime.to_string(request.requested_date) or '',
                    'reason': request.reason,
                    'can_decide': is_approver,
                    'can_cancel': is_approver or request.requested_by_id == self.env.user,
                } if request else False,
            })
        self.env['engineering.change'].flush_model(['affected_project_ids'])
        running = self.env['engineering.change'].search([
            ('affected_project_ids', 'in', job.id), ('state', 'not in', list(RUNNING_CHANGE_EXCLUDED_STATES)),
        ], order='id desc')
        return {
            'id': job.id,
            'name': job.display_name,
            'model': job.model_id.name or '',
            'model_id': job.model_id.id,
            'customer': job.partner_id.name or '',
            'serial': job.machine_serial or '',
            'ready': sum(1 for row in rows if row['required'] and (row['pinned'] or row['current'])),
            'required': sum(1 for row in rows if row['required']),
            'rows': rows,
            'changes': [Sheet._change_summary(change) for change in running],
        }

    @api.model
    def job_print(self, job_id, type_ids):
        """Pin what isn't pinned yet, and return the Job's sheets to print."""
        job = self.env['project.project'].browse(job_id).exists()
        if not job:
            raise UserError(_("This Job no longer exists."))
        return self._pin(job, self.env['qc.checksheet.type'].browse(type_ids).exists()).ids

    # Printing

    def _print_files(self, combined=False):
        """(file name, content, mimetype) of these Job sheets, rendered with the user's own rights."""
        if not self:
            raise UserError(_("Select at least one check sheet to print."))
        self.check_access('read')
        Report = self.env['ir.actions.report']
        prefix = self[0]._file_prefix()
        if len(self) == 1:
            pdf, _type = Report._render_qweb_pdf(JOB_REPORT_NAME, self.ids)
            return f'{self.pdf_file_name}.pdf', pdf, 'application/pdf'
        if combined:
            pdf, _type = Report._render_qweb_pdf(JOB_REPORT_NAME, self.ids)
            return f'{prefix}-QC-ALL.pdf', pdf, 'application/pdf'
        buffer = io.BytesIO()
        taken = set()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
            for rec in self:
                pdf, _type = Report._render_qweb_pdf(JOB_REPORT_NAME, rec.ids)
                # Two Types may share a name; a ZIP would silently hold both under one.
                name, counter = rec.pdf_file_name, 1
                while name.upper() in taken:
                    counter += 1
                    name = f'{rec.pdf_file_name} ({counter})'
                taken.add(name.upper())
                archive.writestr(f'{name}.pdf', pdf)
        return f'{prefix}-QC.zip', buffer.getvalue(), 'application/zip'

    def action_open_checksheet(self):
        self.ensure_one()
        return self.checksheet_id.action_open_editor() if self.checksheet_type == 'standard' else {
            'type': 'ir.actions.act_window',
            'res_model': 'qc.checksheet',
            'res_id': self.checksheet_id.id,
            'view_mode': 'form',
        }
