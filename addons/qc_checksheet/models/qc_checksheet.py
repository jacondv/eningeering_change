import hashlib

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

GROUP_USER = 'qc_checksheet.group_qc_user'
GROUP_AUTHOR = 'qc_checksheet.group_qc_author'
GROUP_APPROVER = 'qc_checksheet.group_qc_approver'
GROUP_ADMIN = 'qc_checksheet.group_qc_admin'
ACTIVITY_TODO = 'mail.mail_activity_data_todo'
# The highest Revision a sheet may start at when it comes over from paper (see _start_at_revision).
MAX_START_REVISION = 99
# A sheet's first Revision is 1, not 0.
FIRST_REVISION = 1


class QcChecksheet(models.Model):
    """One Revision of a Model's check sheet. A Model holds one sheet per
    Type; all Revisions of it share `root_id`, and each keeps its own full
    copy of the content, so any old Revision can still be opened and printed
    exactly as it was issued. Jobs don't own sheets: each Job pins the
    Revision it is checked against (qc.job.checksheet), so a later Revision
    of the Model never changes what an earlier Job uses.

    Edit guards live in create()/write()/unlink() and are skipped under
    sudo: the workflow methods below check the user's group themselves, then
    change workflow fields through sudo().
    """
    _name = 'qc.checksheet'
    _description = 'QC Check Sheet'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'
    _rec_names_search = ['name', 'reference', 'model_id.name']
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
        'image_group_ids', 'approval_ids', 'history_ids', 'change_request_ids',
    })

    name = fields.Char(
        required=True, tracking=True,
        help="Printed as the Header of the report, with the Type's name below it. "
             "Filled in from the Product Family's Description when the Model has one.")
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
    revision = fields.Integer(string='Rev', default=FIRST_REVISION, readonly=True, copy=False, tracking=True)
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

    model_id = fields.Many2one(
        'equipment.model', string='Model', index=True, tracking=True, ondelete='restrict')
    machine_model = fields.Char(related='model_id.name', store=True, string='Model Name')

    # The copied lines keep their source's line_key, so the editor can compare
    # this sheet with the one it was copied from.
    copied_from_id = fields.Many2one('qc.checksheet', string='Copied From', readonly=True, copy=False)

    group_ids = fields.One2many('qc.checksheet.group', 'checksheet_id', string='Inspection Groups')
    panel_line_ids = fields.One2many('qc.checksheet.panel.line', 'checksheet_id', string='Panel Lines')
    image_group_ids = fields.One2many('qc.checksheet.image.group', 'checksheet_id', string='Image Groups')
    approval_ids = fields.One2many('qc.checksheet.approval', 'checksheet_id', string='Approval')
    history_ids = fields.One2many('qc.checksheet.history', 'checksheet_id', string='Revision History')
    job_sheet_ids = fields.One2many('qc.job.checksheet', 'checksheet_id', string='Jobs Using It')
    job_count = fields.Integer(string='Jobs', compute='_compute_job_count', help="Jobs pinned to this Revision.")
    # Every Revision of this sheet: the Jobs are told apart by the Revision they are pinned to.
    root_job_sheet_ids = fields.Many2many(
        'qc.job.checksheet', string='Jobs Using This Sheet', compute='_compute_root_job_sheets')
    sheet_job_count = fields.Integer(
        string='Jobs Using This Sheet', compute='_compute_root_job_sheets',
        help="Jobs pinned to any Revision of this sheet.")
    remarks = fields.Text()

    item_count = fields.Integer(compute='_compute_item_count')

    _model_type_revision_unique = models.Constraint(
        'UNIQUE(model_id, type_id, revision)',
        'This Model already has a check sheet of this Type.',
    )

    @api.depends('group_ids.item_ids', 'panel_line_ids')
    def _compute_item_count(self):
        for rec in self:
            if rec.checksheet_type == 'panel_sticker':
                rec.item_count = len(rec.panel_line_ids)
            else:
                rec.item_count = sum(len(g.item_ids) for g in rec.group_ids)

    @api.depends('job_sheet_ids')
    def _compute_job_count(self):
        for rec in self:
            rec.job_count = len(rec.sudo().job_sheet_ids)

    @api.depends('root_id', 'root_id.revision_ids.job_sheet_ids')
    def _compute_root_job_sheets(self):
        JobSheet = self.env['qc.job.checksheet']
        by_root = {}
        for job_sheet in JobSheet.search([('root_id', 'in', self.root_id.ids)]):
            by_root[job_sheet.root_id] = by_root.get(job_sheet.root_id, JobSheet) | job_sheet
        for rec in self:
            job_sheets = by_root.get(rec.root_id, JobSheet)
            rec.root_job_sheet_ids = job_sheets
            rec.sheet_job_count = len(job_sheets)

    def action_view_jobs(self):
        """The Jobs using any Revision of this sheet, grouped by the Revision they print."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Jobs using %s", self.reference or self.name),
            'res_model': 'qc.job.checksheet',
            'view_mode': 'list,form',
            'views': [(False, 'list'), (False, 'form')],
            'domain': [('root_id', '=', self.root_id.id)],
            'context': {'create': False, 'search_default_group_revision': 1},
        }

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

    @api.depends('name', 'reference', 'model_id', 'revision')
    def _compute_display_name(self):
        for rec in self:
            # The Number already names the Model.
            parts = [rec.reference or rec.name, not rec.reference and rec.model_id.display_name, f'Rev {rec.revision}']
            rec.display_name = ' · '.join(part for part in parts if part)

    @staticmethod
    def _family_header(family):
        # Family Description is multi-line text, Header is a single line.
        return ' '.join((family.description or '').split())

    @api.onchange('model_id')
    def _onchange_model_id(self):
        family = self.model_id.sudo().family_id
        header = self._family_header(family)
        if not header:
            return
        # Keep following the Model until the user types a Header of their own.
        family_headers = self.env['equipment.model.family'].sudo().search([
            ('description', '!=', False),
        ]).mapped(self._family_header)
        if not self.name or self.name in family_headers:
            self.name = header

    def _content_signature(self):
        """A fingerprint of everything a printed sheet shows, ids and line keys left out: two sheets with the
        same one print the same. Used to find sheets that could be one."""
        self.ensure_one()
        parts = [
            self.checksheet_type, self.name or '', self.remarks or '',
            [approval.position for approval in self.approval_ids.sorted(lambda a: (a.sequence, a.id))],
        ]
        if self.checksheet_type == 'panel_sticker':
            parts.append([(
                line.item_number, line.part_number, line.description, line.qty, line.note,
                hashlib.sha1(line.image or b'').hexdigest(),
            ) for line in self.panel_line_ids.sorted(lambda l: (l.sequence, l.id))])
            parts.append([(group.name, [(
                line.description, line.size_percent, line.width_percent, line.page_break_after,
                line.keep_original_size, hashlib.sha1(line.image or b'').hexdigest(),
            ) for line in group.image_line_ids.sorted(lambda l: (l.sequence, l.id))]
            ) for group in self.image_group_ids.sorted(lambda g: (g.sequence, g.id))])
        else:
            parts.append([(group.name, [
                (item.description, item.acceptance, item.note)
                for item in group.item_ids.sorted(lambda i: (i.sequence, i.id))
            ]) for group in self.group_ids.sorted(lambda g: (g.sequence, g.id))])
        return hashlib.sha1(repr(parts).encode()).hexdigest()

    @api.model
    def _check_not_shared(self, model_id, type_id):
        share = self.env['qc.checksheet.share'].sudo().search(
            [('model_id', '=', model_id), ('type_id', '=', type_id)], limit=1)
        if share:
            raise UserError(_(
                "This Model uses the sheet of %s for this Type. Go back to a sheet of its own first.",
                share.source_model_id.display_name))

    @api.model
    def _check_start_revision(self, start, model_id, type_id):
        """The Revision a sheet new to Odoo starts at: 1, or the Revision it already has on paper, up to
        MAX_START_REVISION. Only the first sheet of a Model and Type may start above 1: later ones follow on."""
        if not isinstance(start, int) or isinstance(start, bool) or not FIRST_REVISION <= start <= MAX_START_REVISION:
            raise UserError(_("Start at a Revision from %(first)s to %(last)s.", first=FIRST_REVISION, last=MAX_START_REVISION))
        if start > FIRST_REVISION and self.search_count([('model_id', '=', model_id), ('type_id', '=', type_id)]):
            raise UserError(_("This Model already has a sheet of this Type, so its Revisions follow on from it."))

    def _start_at_revision(self, start):
        """Make this new Draft Rev 1 start at Rev `start`: the Revisions before it were made on paper, and are
        listed in its Revision History as rows to fill in, marked 'To be updated'."""
        self.ensure_one()
        if not start or start == FIRST_REVISION:
            return
        sudo_self = self.sudo()
        if self.state != 'draft' or self.previous_revision_id or len(sudo_self.root_id.revision_ids) > 1:
            raise UserError(_("Only a new Draft first Revision can start at another Revision."))
        sudo_self.revision = start
        sudo_self.history_ids.write({'rev': start})
        self.env['qc.checksheet.history'].sudo().create([{
            'checksheet_id': self.id,
            'rev': rev,
            'description': _("To be updated"),
            'date': False,
            'legacy': True,
        } for rev in range(FIRST_REVISION, start)])

    @api.model
    def _generate_reference(self, checksheet_type, model):
        if not checksheet_type:
            raise UserError(_("A check sheet needs a Type."))
        if not model:
            raise UserError(_("A check sheet needs a Model."))
        return f'QC-{checksheet_type.code}-{model.name}'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not self.env.su and self.WORKFLOW_FIELDS & vals.keys():
                raise UserError(_("Status, Revision and Number are set by the system."))
            if vals.get('model_id') and vals.get('type_id'):
                self._check_not_shared(vals['model_id'], vals['type_id'])
            vals['reference'] = vals.get('reference') or self._generate_reference(
                self.env['qc.checksheet.type'].browse(vals.get('type_id')),
                self.env['equipment.model'].browse(vals.get('model_id')),
            )
        records = super().create(vals_list)
        for record in records:
            if not record.root_id:
                record.sudo().root_id = record
            if not record.history_ids:
                self.env['qc.checksheet.history'].sudo().create({
                    'checksheet_id': record.id,
                    'rev': record.revision,
                    'description': _("Initial release"),
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
            for field_name in ('model_id', 'type_id'):
                if rec[field_name] and field_name in vals and rec[field_name].id != vals[field_name]:
                    raise UserError(_(
                        "Model and Type can't be changed once set. "
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
        """Start this first Revision from another Released sheet, usually another
        Model's. The content comes over; its identity and history don't.
        """
        self.ensure_one()
        # The same Type, never another that merely looks alike: its content is not meant for this one.
        if source.type_id != self.type_id:
            raise UserError(_("Can only copy content from a check sheet of the same Type."))
        if source.state != 'released':
            raise UserError(_("Can only copy content from a Released check sheet."))
        if self.state != 'draft' or self.previous_revision_id:
            raise UserError(_("Can only copy content into a Draft first Revision."))
        if self.group_ids or self.panel_line_ids:
            raise UserError(_("This check sheet already has content."))

        self.approval_ids.unlink()
        self.write({'remarks': source.remarks})
        self._copy_lines_from(source)

        sudo_self = self.sudo()
        sudo_self.copied_from_id = source
        sudo_self.history_ids.write({
            'description': _(
                "Adapted from %(number)s Rev %(rev)s",
                number=source.reference or source.name, rev=source.revision),
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

    def _log(self, body):
        """Say what happened on the sheet and on its Model's chatter, which is the one the Model QC page shows."""
        for rec in self:
            rec.sudo().message_post(body=body)
            if rec.model_id:
                rec.model_id.sudo().message_post(body=_(
                    "%(type)s Rev %(rev)s: %(what)s", type=rec.type_id.name, rev=rec.revision, what=body))

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
                'reference': rec.reference or self._generate_reference(rec.type_id, rec.model_id),
            })
            rec._clear_workflow_activities()
            rec._log(_("Submitted for approval by %s.", self.env.user.name))
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
            rec._log(_("Recalled to Draft by %s.", self.env.user.name))

    def action_reject(self, reason):
        self.ensure_one()
        self._check_group(GROUP_APPROVER)
        self._check_state('review')
        if not (reason or '').strip():
            raise UserError(_("Enter the reason for rejecting."))
        sudo_self = self.sudo()
        sudo_self.write({'state': 'draft', 'reject_reason': reason})
        self._clear_workflow_activities()
        self._log(_("Rejected by %(user)s: %(reason)s", user=self.env.user.name, reason=reason))
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
            rec._log(
                _("Released by %s. Jobs printing this sheet from now on get it.", self.env.user.name)
                if not previous else
                _("Released by %(user)s, replacing Rev %(old)s. Jobs printing this sheet from now on get it; "
                  "Jobs that already printed Rev %(old)s keep it until they are updated.",
                  user=self.env.user.name, old=previous[0].revision))

    def action_create_revision(self, reason, change_ids=None):
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
                'legacy': line.legacy,
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
            'model_id': self.model_id.id,
            'remarks': self.remarks,
            'revision': next_revision,
            'root_id': self.root_id.id,
            'previous_revision_id': self.id,
            'copied_from_id': self.copied_from_id.id,
            'history_ids': history,
            'change_request_ids': [(6, 0, self.env['engineering.change'].browse(change_ids or []).exists().ids)],
        })
        new_revision._copy_lines_from(self.sudo())
        new_revision._log(_("Opened by %(user)s from Rev %(old)s: %(reason)s", user=self.env.user.name, old=self.revision, reason=reason.strip()))
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
