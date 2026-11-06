from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

GROUP_AUTHOR = 'qc_checksheet.group_qc_author'
GROUP_APPROVER = 'qc_checksheet.group_qc_approver'
GROUP_ADMIN = 'qc_checksheet.group_qc_admin'
ACTIVITY_TODO = 'mail.mail_activity_data_todo'


class QcChecksheet(models.Model):
    """One Revision of a check sheet. All Revisions of the same sheet share
    `root_id`, and each keeps its own full copy of the content, so any old
    Revision can still be opened and printed exactly as it was issued. A
    sheet is identified by Number + Job + Rev: Number comes from the Type and
    the Model, so other Jobs of the same Model carry the same Number.

    Edit guards live in create()/write()/unlink() and are skipped under
    sudo: the workflow methods below check the user's group themselves, then
    change workflow fields through sudo().
    """
    _name = 'qc.checksheet'
    _description = 'QC Check Sheet'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'
    _rec_names_search = ['name', 'reference', 'job_number.name']
    # Approvers and read-only users can comment without having write access.
    _mail_post_access = 'read'

    # Only ever changed by the workflow methods, never through a direct write.
    WORKFLOW_FIELDS = frozenset({
        'state', 'revision', 'root_id', 'previous_revision_id', 'reference', 'copied_from_id',
        'reject_reason', 'submitted_by_id', 'submitted_date', 'approved_by_id', 'approved_date', 'editor_version',
    })
    # Editing any of these is a content change, so it needs a Draft Revision.
    CONTROLLED_FIELDS = frozenset({
        'name', 'company_id', 'remarks', 'group_ids', 'panel_line_ids',
        'image_group_ids', 'approval_ids', 'history_ids',
    })

    # What a copied Rev 0 must keep exactly as its source had it. Header and
    # Revision History stay editable: they describe this machine and this Rev.
    COPY_LOCKED_FIELDS = frozenset({
        'remarks', 'group_ids', 'panel_line_ids', 'image_group_ids', 'approval_ids',
    })

    name = fields.Char(
        required=True, tracking=True,
        help="Printed as the Header of the report, with the Type's name below it. "
             "Filled in from the Product Family's Description when the Job has one.")
    reference = fields.Char(
        string='Number', readonly=True, copy=False, tracking=True,
        help="QC-<Type Code>-<Model Name>. Generated once, then kept even if the Model is renamed.")
    type_id = fields.Many2one(
        'qc.checksheet.type', string='Type', ondelete='restrict', tracking=True, index=True)
    checksheet_type = fields.Selection(related='type_id.layout', store=True, string='Layout')
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('review', 'In Review'),
        ('released', 'Released'),
        ('superseded', 'Superseded'),
    ], default='draft', required=True, readonly=True, copy=False, tracking=True, index=True)
    revision = fields.Integer(string='Rev', default=0, readonly=True, copy=False, tracking=True)
    root_id = fields.Many2one(
        'qc.checksheet', string='First Revision', readonly=True, copy=False, index=True,
        ondelete='cascade')
    previous_revision_id = fields.Many2one(
        'qc.checksheet', string='Previous Revision', readonly=True, copy=False, ondelete='set null')
    revision_ids = fields.One2many('qc.checksheet', 'root_id', string='Revisions')
    revision_count = fields.Integer(compute='_compute_revision_count')
    change_reason = fields.Char(string='Reason for Change', compute='_compute_change_reason')
    reject_reason = fields.Char(string='Reject Reason', readonly=True, copy=False)
    submitted_by_id = fields.Many2one('res.users', string='Submitted By', readonly=True, copy=False)
    submitted_date = fields.Datetime(string='Submitted On', readonly=True, copy=False)
    approved_by_id = fields.Many2one('res.users', string='Approved By', readonly=True, copy=False)
    approved_date = fields.Date(string='Approved On', readonly=True, copy=False)

    job_number = fields.Many2one('project.project', string='Job Number', index=True, tracking=True)
    machine_serial = fields.Char(related='job_number.machine_serial', store=True, string='Machine Serial')
    machine_model = fields.Char(related='job_number.model_id.name', store=True, string='Model')
    engine_number = fields.Char(related='job_number.engine_serial', store=True, string='Engine Number')
    customer = fields.Char(related='job_number.partner_id.name', store=True, string='Customer')
    check_date = fields.Date(string='Check Date')

    copied_from_id = fields.Many2one('qc.checksheet', string='Copied From', readonly=True, copy=False)
    content_locked = fields.Boolean(
        compute='_compute_content_locked',
        help="Rev 0 copied from another Job keeps exactly the content it was copied from: "
             "release it, then create a New Revision to change what is inspected.")

    group_ids = fields.One2many('qc.checksheet.group', 'checksheet_id', string='Inspection Groups')
    panel_line_ids = fields.One2many('qc.checksheet.panel.line', 'checksheet_id', string='Panel Lines')
    image_group_ids = fields.One2many('qc.checksheet.image.group', 'checksheet_id', string='Image Groups')
    approval_ids = fields.One2many('qc.checksheet.approval', 'checksheet_id', string='Approval')
    history_ids = fields.One2many('qc.checksheet.history', 'checksheet_id', string='Revision History')
    remarks = fields.Text()

    item_count = fields.Integer(compute='_compute_item_count')

    _job_type_revision_unique = models.Constraint(
        'UNIQUE(job_number, type_id, revision)',
        'This Job already has a check sheet of this Type.',
    )

    @api.depends('group_ids.item_ids', 'panel_line_ids')
    def _compute_item_count(self):
        for rec in self:
            if rec.checksheet_type == 'panel_sticker':
                rec.item_count = len(rec.panel_line_ids)
            else:
                rec.item_count = sum(len(g.item_ids) for g in rec.group_ids)

    @api.depends('copied_from_id', 'revision')
    def _compute_content_locked(self):
        for rec in self:
            rec.content_locked = bool(rec.copied_from_id) and rec.revision == 0

    def _content_locked_message(self):
        self.ensure_one()
        return _(
            "%(sheet)s is a copy of %(source)s and keeps exactly the same content at Rev 0. "
            "Release it first, then create a New Revision to change what is inspected.",
            sheet=self.display_name, source=self.copied_from_id.display_name)

    @api.depends('root_id.revision_ids')
    def _compute_revision_count(self):
        for rec in self:
            rec.revision_count = len(rec.root_id.revision_ids)

    @api.depends('revision', 'history_ids.rev', 'history_ids.description')
    def _compute_change_reason(self):
        for rec in self:
            rec.change_reason = rec._current_history_line().description

    def _current_history_line(self):
        self.ensure_one()
        return self.history_ids.filtered(lambda h: h.rev == self.revision)[:1]

    @api.depends('name', 'reference', 'job_number', 'revision')
    def _compute_display_name(self):
        for rec in self:
            parts = [rec.reference or rec.name, rec.job_number.display_name, f'Rev {rec.revision}']
            rec.display_name = ' · '.join(part for part in parts if part)

    @staticmethod
    def _family_header(family):
        # Family Description is multi-line text, Header is a single line.
        return ' '.join((family.description or '').split())

    @api.onchange('job_number')
    def _onchange_job_number(self):
        family = self.job_number.sudo().model_id.family_id
        header = self._family_header(family)
        if not header:
            return
        # Keep following the Job until the user types a Header of their own.
        family_headers = self.env['equipment.model.family'].sudo().search([
            ('description', '!=', False),
        ]).mapped(self._family_header)
        if not self.name or self.name in family_headers:
            self.name = header

    @api.model
    def _generate_reference(self, checksheet_type, job):
        if not checksheet_type:
            raise UserError(_("A check sheet needs a Type."))
        if not job:
            raise UserError(_("A check sheet needs a Job Number."))
        if not job.model_id:
            raise UserError(_("Job %s has no Model. Set its Model first.", job.display_name))
        return f'QC-{checksheet_type.code}-{job.model_id.name}'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not self.env.su and self.WORKFLOW_FIELDS & vals.keys():
                raise UserError(_("Status, Revision and Number are set by the system."))
            vals['reference'] = vals.get('reference') or self._generate_reference(
                self.env['qc.checksheet.type'].browse(vals.get('type_id')),
                self.env['project.project'].browse(vals.get('job_number')),
            )
        records = super().create(vals_list)
        for record in records:
            if not record.root_id:
                record.sudo().root_id = record
            if not record.history_ids:
                self.env['qc.checksheet.history'].sudo().create({
                    'checksheet_id': record.id,
                    'rev': record.revision,
                    'description': _("Initial issue"),
                    'created_by': self.env.user.name,
                })
        return records

    def write(self, vals):
        if not self.env.su:
            self._check_write_allowed(vals)
        return super().write(vals)

    def _check_write_allowed(self, vals):
        if self.WORKFLOW_FIELDS & vals.keys():
            raise UserError(_("Status, Revision and Number are set by the system."))
        for rec in self:
            if rec.state != 'draft' and self.CONTROLLED_FIELDS & vals.keys():
                raise UserError(_(
                    "%s is locked. Create a New Revision to change it.", rec.display_name))
            if rec.content_locked and self.COPY_LOCKED_FIELDS & vals.keys():
                raise UserError(rec._content_locked_message())
            if rec.state == 'superseded' and 'check_date' in vals:
                raise UserError(_("%s is superseded and can't be changed.", rec.display_name))
            for field_name in ('job_number', 'type_id'):
                if rec[field_name] and field_name in vals and rec[field_name].id != vals[field_name]:
                    raise UserError(_(
                        "Job Number and Type can't be changed once set. "
                        "Delete the Draft and create it again."))

    def unlink(self):
        if not self.env.su:
            locked = self.filtered(lambda rec: rec.state != 'draft')
            if locked and not self.env.user.has_group(GROUP_ADMIN):
                raise UserError(_("Only a Draft can be deleted."))
            if locked.root_id.revision_ids - self:
                raise UserError(_(
                    "An issued Revision can only be deleted together with all other Revisions "
                    "of the same sheet. Select them all using the All Revisions filter."))
        return super().unlink()

    def _copy_lines_from(self, source):
        """Copy the Approval positions, then Groups/Items or Images/Panel Lines,
        keeping each line's line_key so Revisions can be compared line by line."""
        self.ensure_one()
        for approval in source.approval_ids:
            self.env['qc.checksheet.approval'].create({
                'checksheet_id': self.id,
                'sequence': approval.sequence,
                'position': approval.position,
            })

        if self.checksheet_type == 'panel_sticker':
            for line in source.panel_line_ids:
                self.env['qc.checksheet.panel.line'].create({
                    'checksheet_id': self.id,
                    'line_key': line.line_key,
                    'sequence': line.sequence,
                    'item_number': line.item_number,
                    'part_number': line.part_number,
                    'description': line.description,
                    'image': line.image,
                    'qty': line.qty,
                    'note': line.note,
                })
            for image_group in source.image_group_ids:
                self.env['qc.checksheet.image.group'].create({
                    'checksheet_id': self.id,
                    'line_key': image_group.line_key,
                    'sequence': image_group.sequence,
                    'name': image_group.name,
                    'image_line_ids': [
                        (0, 0, {
                            'line_key': line.line_key,
                            'sequence': line.sequence,
                            'image': line.image,
                            'description': line.description,
                            'size_percent': line.size_percent,
                            'width_percent': line.width_percent,
                            'page_break_after': line.page_break_after,
                            'keep_original_size': line.keep_original_size,
                        }) for line in image_group.image_line_ids
                    ],
                })
        else:
            for group in source.group_ids:
                self.env['qc.checksheet.group'].create({
                    'checksheet_id': self.id,
                    'line_key': group.line_key,
                    'sequence': group.sequence,
                    'name': group.name,
                    'item_ids': [
                        (0, 0, {
                            'line_key': item.line_key,
                            'sequence': item.sequence,
                            'description': item.description,
                            'acceptance': item.acceptance,
                            'note': item.note,
                        }) for item in group.item_ids
                    ],
                })

    def _copy_content_from(self, source):
        """Start this new machine's Rev 0 from another Job's current Released
        Revision. The content comes over; everything specific to the old
        machine (identity, check date, history) deliberately does not.
        """
        self.ensure_one()
        if source.checksheet_type != self.checksheet_type:
            raise UserError(_("Can only copy content from a check sheet of the same Type."))
        if source.state != 'released':
            raise UserError(_("Can only copy content from a Released check sheet."))
        if self.state != 'draft' or self.revision != 0:
            raise UserError(_("Can only copy content into a Draft Rev 0."))
        if self.group_ids or self.panel_line_ids:
            raise UserError(_("This check sheet already has content."))

        self.approval_ids.unlink()
        self.write({'remarks': source.remarks})
        self._copy_lines_from(source)

        sudo_self = self.sudo()
        sudo_self.copied_from_id = source
        sudo_self.history_ids.write({
            'description': _(
                "Initial issue - copied from %(job)s / %(name)s Rev %(rev)s",
                job=source.job_number.display_name, name=source.name, rev=source.revision),
        })

    def _check_group(self, group):
        if not self.env.su and not self.env.user.has_group(group):
            raise AccessError(_("You don't have the access rights for this action."))

    def _check_state(self, state):
        for rec in self:
            if rec.state != state:
                raise UserError(_(
                    "%(sheet)s must be %(state)s for this action.",
                    sheet=rec.display_name,
                    state=dict(self._fields['state'].selection)[state]))

    def _clear_workflow_activities(self):
        self.sudo().activity_unlink([ACTIVITY_TODO])

    def action_submit(self):
        self._check_group(GROUP_AUTHOR)
        self._check_state('draft')
        approvers = self.env.ref(GROUP_APPROVER).sudo().user_ids
        for rec in self:
            if not rec.item_count:
                raise UserError(_("%s has no content to submit.", rec.display_name))
            rec._check_content_complete()
            sudo_rec = rec.sudo()
            line = rec._current_history_line()
            if line and not line.description:
                raise UserError(_("Enter the Description of this Revision in Revision History."))
            sudo_rec.write({
                'state': 'review',
                'submitted_by_id': self.env.uid,
                'submitted_date': fields.Datetime.now(),
                'reject_reason': False,
                'reference': rec.reference or self._generate_reference(rec.type_id, rec.job_number),
            })
            rec._clear_workflow_activities()
            for approver in approvers:
                sudo_rec.activity_schedule(
                    ACTIVITY_TODO, user_id=approver.id,
                    summary=_("Approve %s", rec.display_name))

    def action_recall(self):
        self._check_group(GROUP_AUTHOR)
        self._check_state('review')
        self.sudo().write({'state': 'draft'})
        self._clear_workflow_activities()
        for rec in self:
            rec.sudo().message_post(body=_("Recalled to Draft by %s.", self.env.user.name))

    def action_reject(self, reason):
        self.ensure_one()
        self._check_group(GROUP_APPROVER)
        self._check_state('review')
        if not (reason or '').strip():
            raise UserError(_("Enter the reason for rejecting."))
        sudo_self = self.sudo()
        sudo_self.write({'state': 'draft', 'reject_reason': reason})
        self._clear_workflow_activities()
        sudo_self.message_post(body=_("Rejected by %(user)s: %(reason)s", user=self.env.user.name, reason=reason))
        if self.submitted_by_id:
            sudo_self.activity_schedule(
                ACTIVITY_TODO, user_id=self.submitted_by_id.id,
                summary=_("Rejected: %s", self.display_name), note=reason)

    def action_approve(self):
        self._check_group(GROUP_APPROVER)
        self._check_state('review')
        today = fields.Date.context_today(self)
        for rec in self:
            sudo_rec = rec.sudo()
            previous = sudo_rec.root_id.revision_ids.filtered(lambda r: r.state == 'released')
            previous.write({'state': 'superseded'})
            sudo_rec.write({'state': 'released', 'approved_by_id': self.env.uid, 'approved_date': today})
            line = sudo_rec._current_history_line()
            line.write({'date': line.date or today, 'approved_by': self.env.user.name})
            rec._clear_workflow_activities()
            if previous:
                sudo_rec.message_post(body=_(
                    "Rev %(new)s is now current. Withdraw printed copies of Rev %(old)s from the workshop.",
                    new=rec.revision, old=previous[0].revision))

    def action_create_revision(self, reason):
        """Open the next Draft Revision. This one stays Released, and in use,
        until the new Revision is approved (see action_approve)."""
        self.ensure_one()
        self._check_group(GROUP_AUTHOR)
        self._check_state('released')
        if not (reason or '').strip():
            raise UserError(_("Enter the reason for this change."))
        revisions = self.root_id.revision_ids
        if revisions.filtered(lambda r: r.state in ('draft', 'review')):
            raise UserError(_("This sheet already has a new Revision in progress."))

        next_revision = max(revisions.mapped('revision')) + 1
        history = [
            (0, 0, {
                'rev': line.rev,
                'description': line.description,
                'date': line.date,
                'created_by': line.created_by,
                'approved_by': line.approved_by,
                'show_in_report': line.show_in_report,
            }) for line in self.history_ids
        ]
        history.append((0, 0, {
            'rev': next_revision,
            'description': reason,
            'created_by': self.env.user.name,
        }))
        new_revision = self.sudo().create({
            'name': self.name,
            'reference': self.reference,
            'type_id': self.type_id.id,
            'company_id': self.company_id.id,
            'job_number': self.job_number.id,
            'remarks': self.remarks,
            'revision': next_revision,
            'root_id': self.root_id.id,
            'previous_revision_id': self.id,
            'copied_from_id': self.copied_from_id.id,
            'history_ids': history,
        })
        new_revision._copy_lines_from(self.sudo())
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': new_revision.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_revisions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Revisions: %s", self.reference or self.name),
            'res_model': self._name,
            'view_mode': 'list,form',
            'views': [(self.env.ref('qc_checksheet.view_qc_checksheet_revision_list').id, 'list'), (False, 'form')],
            'domain': [('root_id', '=', self.root_id.id)],
            'context': {'create': False},
        }

    def action_open_current_revision(self):
        self.ensure_one()
        revisions = self.root_id.revision_ids
        current = revisions.filtered(lambda r: r.state == 'released')[:1] or revisions.sorted('revision')[-1]
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': current.id,
            'view_mode': 'form',
            'target': 'current',
        }
