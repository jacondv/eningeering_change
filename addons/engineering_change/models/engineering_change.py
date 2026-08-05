from odoo import _, api, fields, models
from odoo.addons.base.models.res_users import check_identity
from odoo.exceptions import AccessError, UserError, ValidationError


class EngineeringChange(models.Model):
    """Core record: fields, computed UX hints, and the field-level edit
    guards enforced in write(). The state machine itself lives in
    engineering_change_workflow.py, and read-only navigation/reporting
    (stat buttons, Dashboard) lives in engineering_change_reporting.py -
    both extend this model via _inherit.
    """
    _name = 'engineering.change'
    _description = 'Engineering Change Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    # Field-level edit segregation, enforced in write() (see _check_field_edit_permissions):
    # - ENGINEER_FIELDS: the technical content of the request. Only the Engineer/Request
    #   role may touch them, and only while the request is still in Draft - once
    #   submitted (let alone approved), the content is frozen. If it needs correction,
    #   the approver rejects it back to Draft instead of editing it directly.
    # - MANAGER_FIELDS: the operational/execution side. Only BOD/Manager Approve may
    #   touch them, and never once the request is Done (reopen first).
    # - request_type is the one deliberate exception: both Engineer and Manager may
    #   change it, and Manager may still change it up to the Manager approval step
    #   (matches the original requirement to let the type be corrected right before
    #   that approval).
    ENGINEER_FIELDS = frozenset({
        'title', 'description', 'engineer_id', 'rpn', 'change_category',
        'impact_lead_time', 'impact_safety', 'impact_compliance',
        'image_ids', 'document_ids', 'default_affected_model_ids',
        'default_affected_project_ids',
    })
    MANAGER_FIELDS = frozenset({'implement_team_ids', 'implement_owner_id'})
    # Fields only ever meant to change as a side effect of the workflow methods
    # below (Submit/Approve/Reject/Close/Reopen), never through a direct write().
    # Base ACL + the rules above already grant write=1 on the whole model to
    # Request/BOD/Manager Approve, so without this guard any of them could set
    # state directly (e.g. skip straight to 'done'), bypassing the approval
    # sequence entirely.
    WORKFLOW_FIELDS = frozenset({
        'state', 'bod_approver_id', 'dcr_no', 'close_date', 'reject_reason',
    })

    name = fields.Char(string='Request No', default='New', readonly=True, copy=False, tracking=True)
    request_type = fields.Selection([
        ('minor', 'Minor Change'),
        ('dcr', 'DCR'),
    ], string='Request Type', required=True, default='minor', tracking=True)
    dcr_no = fields.Char(string='DCR No', readonly=True, copy=False, index=True, tracking=True)
    change_category = fields.Selection([
        ('standard', 'Standard'),
        ('client_feedback', 'Client Feedback'),
        ('supplychain', 'SupplyChain'),
        ('safety', 'Safety'),
        ('productivity', 'Productivity'),
        ('production', 'Production')
    ], string='Change Source', tracking=True)
    title = fields.Char(required=True, tracking=True)
    description = fields.Html(required=True)
    engineer_id = fields.Many2one(
        'res.users', string='Engineer', required=True, index=True,
        default=lambda self: self.env.user, tracking=True)
    close_date = fields.Datetime(readonly=True, copy=False)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('waiting_manager_approval', 'Manager Approval'),
        ('bod_review', 'BOD Approval'),
        ('implement', 'Design'),
        ('production', 'Production'),
        ('sale', 'Sales'),
        ('done', 'Closed'),
    ], default='draft', copy=False, tracking=True, index=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)
    active = fields.Boolean(default=True)
    project_id = fields.Many2one(
        'project.project', string='Project', readonly=True, copy=False, ondelete='restrict',
        help="Container Project (named after the Request No) that this "
             "request's Actions/Tasks are filed under, instead of Private. "
             "Created automatically on Submit, once the Request No is assigned. "
             "ondelete='restrict': this Project may only be deleted as a side "
             "effect of deleting this request (see unlink() below) - deleting "
             "it directly would silently orphan the request and, worse, "
             "bypass the password confirmation required to delete a request.")

    image_ids = fields.One2many('engineering.change.image', 'change_id', string='Images')
    document_ids = fields.One2many('engineering.change.document', 'change_id', string='Related Drawings')
    task_ids = fields.One2many('project.task', 'change_id', string='Actions')

    implement_team_ids = fields.Many2many(
        'res.users', 'engineering_change_implement_team_rel', 'change_id', 'user_id',
        string='Implement Team', tracking=True)
    implement_owner_id = fields.Many2one('res.users', string='Implement Owner', tracking=True)

    rpn = fields.Integer(string='RPN', tracking=True)
    rpn_level = fields.Selection([
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
    ], string='RPN Level', compute='_compute_rpn_level', store=True)
    impact_lead_time = fields.Text(string='Lead Time Impact', tracking=True)
    impact_safety = fields.Text(string='Safety Impact', tracking=True)
    impact_compliance = fields.Text(string='Compliance Impact', tracking=True)

    bod_approver_id = fields.Many2one('res.users', string='BOD Approver', readonly=True, copy=False)
    reject_reason = fields.Text(readonly=True, copy=False)

    action_count = fields.Integer(compute='_compute_action_stats')
    action_done_count = fields.Integer(compute='_compute_action_stats')
    progress = fields.Float(compute='_compute_action_stats', string='Progress (%)')
    evidence_count = fields.Integer(compute='_compute_evidence_count')
    affected_model_ids = fields.Many2many(
        'equipment.model', 'engineering_change_affected_model_rel', 'change_id', 'model_id',
        compute='_compute_affected_model_ids', store=True,
        string='Impacted Models')
    default_affected_model_ids = fields.Many2many(
        'equipment.model', 'engineering_change_default_model_rel', 'change_id', 'model_id',
        string='Default Impacted Model',
        help="Pre-fills each new Action's own Impacted Model when created under "
             "this request, since most Actions typically affect the same "
             "Model(s). Each Action can still change or clear it afterward - "
             "this is only a starting value, not kept in sync.")
    affected_project_ids = fields.Many2many(
        'project.project', 'engineering_change_affected_project_rel', 'change_id', 'project_id',
        compute='_compute_affected_project_ids', store=True,
        string='Impacted Job Numbers')
    default_affected_project_ids = fields.Many2many(
        'project.project', 'engineering_change_default_project_rel', 'change_id', 'project_id',
        string='Default Impacted Job Number', domain=[('is_ec_project', '=', False)],
        help="Pre-fills each new Action's own Impacted Job Number when created "
             "under this request, since most Actions typically affect the same "
             "Job Number(s). Each Action can still change or clear it afterward - "
             "this is only a starting value, not kept in sync.")
    has_overdue_action = fields.Boolean(compute='_compute_has_overdue', store=True)
    next_action_deadline = fields.Date(compute='_compute_next_action_deadline', store=True, string='Next Deadline')

    # UX hints for the view (readonly conditions). The write() guard below is the
    # actual enforcement; these just let the form grey fields out accordingly.
    can_edit_engineer_fields = fields.Boolean(compute='_compute_edit_rights')
    can_edit_manager_fields = fields.Boolean(compute='_compute_edit_rights')
    can_edit_request_type = fields.Boolean(compute='_compute_edit_rights')
    can_confirm_production = fields.Boolean(compute='_compute_edit_rights')
    can_confirm_sale = fields.Boolean(compute='_compute_edit_rights')
    can_edit_dcr_no = fields.Boolean(compute='_compute_edit_rights')

    _rpn_non_negative = models.Constraint(
        'CHECK(rpn >= 0)',
        'RPN cannot be negative.',
    )
    _project_id_unique = models.Constraint(
        'UNIQUE(project_id)',
        'Each Project can only be linked to one Engineering Change request.',
    )
    _dcr_no_unique = models.Constraint(
        'UNIQUE(dcr_no)',
        'This DCR Number is already used by another request.',
    )

    # ------------------------------------------------------------
    # Computed fields
    # ------------------------------------------------------------
    @api.depends('rpn')
    def _compute_rpn_level(self):
        for rec in self:
            if rec.rpn >= 100:
                rec.rpn_level = 'high'
            elif rec.rpn >= 50:
                rec.rpn_level = 'medium'
            else:
                rec.rpn_level = 'low'

    @api.depends('task_ids.state')
    def _compute_action_stats(self):
        for rec in self:
            rec.action_count = len(rec.task_ids)
            rec.action_done_count = len(rec.task_ids.filtered(lambda t: t.state == '1_done'))
            rec.progress = (rec.action_done_count / rec.action_count * 100) if rec.action_count else 0.0

    @api.depends('task_ids.evidence_ids')
    def _compute_evidence_count(self):
        for rec in self:
            rec.evidence_count = len(rec.task_ids.evidence_ids)

    @api.depends('task_ids.affected_model_ids')
    def _compute_affected_model_ids(self):
        for rec in self:
            rec.affected_model_ids = rec.task_ids.affected_model_ids

    @api.depends('task_ids.affected_project_ids')
    def _compute_affected_project_ids(self):
        for rec in self:
            rec.affected_project_ids = rec.task_ids.affected_project_ids

    @api.depends('task_ids.is_overdue')
    def _compute_has_overdue(self):
        for rec in self:
            rec.has_overdue_action = any(rec.task_ids.mapped('is_overdue'))

    @api.depends('task_ids.date_deadline', 'task_ids.state')
    def _compute_next_action_deadline(self):
        for rec in self:
            deadlines = rec.task_ids.filtered(
                lambda t: t.state not in ('1_done', '1_canceled') and t.date_deadline
            ).mapped('date_deadline')
            rec.next_action_deadline = fields.Date.to_date(min(deadlines)) if deadlines else False

    @api.depends('state', 'implement_owner_id')
    def _compute_edit_rights(self):
        user = self.env.user
        is_engineer = user.has_group('engineering_change.group_ec_engineer')
        is_manager = user.has_group('engineering_change.group_ec_manager') \
            or user.has_group('base.group_system')
        is_approver = user.has_group('engineering_change.group_ec_bod') or is_manager
        can_edit_dcr_no = user.has_group('engineering_change.group_ec_edit_dcr_no')
        for rec in self:
            rec.can_edit_engineer_fields = is_manager or (is_engineer and rec.state == 'draft')
            rec.can_edit_manager_fields = is_approver and rec.state != 'done'
            rec.can_edit_request_type = (
                is_manager
                or (is_engineer and rec.state == 'draft')
                or (is_approver and rec.state in ('draft', 'waiting_manager_approval'))
            )
            rec.can_confirm_production = is_manager or rec.implement_owner_id == user
            rec.can_confirm_sale = is_manager or rec.implement_owner_id == user
            rec.can_edit_dcr_no = can_edit_dcr_no

    # ------------------------------------------------------------
    # Project linking
    # ------------------------------------------------------------
    def _link_ec_project(self):
        """Find-or-create the project.project named after this request's
        (now-assigned) Request No and set it as `project_id`, moving any
        Actions/Tasks already created pre-Submit (when the request was still
        named "New") onto it - called from action_submit(), once the real
        Request No exists, so requests don't collide on a shared "New"
        project while still in Draft.

        Always creates a brand new project rather than reusing one found by
        name match: `project_id` is 1-1 with the request (enforced by
        `_project_id_unique`), so this must never accidentally attach to a
        pre-existing, unrelated project.project that happens to share the
        same name.

        sudo(): the Engineer submitting isn't necessarily granted create
        rights on project.project.
        """
        self.ensure_one()
        project = self.env['project.project'].sudo().create({
            'name': self.name,
            'is_ec_project': True,
        })
        self.project_id = project.id
        stale_tasks = self.task_ids.filtered(lambda t: t.project_id != project)
        if stale_tasks:
            stale_tasks.sudo().write({'project_id': project.id})

    # ------------------------------------------------------------
    # Constraints
    # ------------------------------------------------------------
    @api.constrains('implement_owner_id', 'implement_team_ids')
    def _check_implement_owner(self):
        for rec in self:
            if rec.implement_owner_id and rec.implement_owner_id not in rec.implement_team_ids:
                raise ValidationError(_("Implement Owner must be a member of the Implement Team."))

    # ------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            engineer_id = vals.get('engineer_id', self.env.user.id)
            if not vals.get('implement_team_ids'):
                vals['implement_team_ids'] = [(6, 0, [engineer_id])]
            if not vals.get('implement_owner_id'):
                vals['implement_owner_id'] = engineer_id
        return super().create(vals_list)

    def unlink(self):
        if not self.env.context.get('ec_delete_password_confirmed'):
            raise UserError(_(
                "Use the Delete button on the request form to permanently delete it - "
                "it will ask you to confirm your password first."))
        # project_id is 1-1 with the request and declares ondelete='restrict'
        # (deleting the Project directly, bypassing this password-confirmed
        # flow, must not silently take the request down with it - see the
        # field's docstring). So instead: delete the requests first (clearing
        # the reference project_id's restrict is guarding), then delete their
        # now-unreferenced projects as a deliberate side effect of this method.
        projects = self.project_id
        result = super().unlink()
        projects.sudo().unlink()
        return result

    @check_identity
    def action_delete_with_password(self):
        """Permanently delete this request, regardless of its stage. Wrapped
        in Odoo's standard password re-check (`check_identity`): the first
        call pops up the core "Access Control" wizard instead of running this
        method, and only calls back into it once the user's password has been
        confirmed - see `res.users.identitycheck` in the `base` module.
        Deletion is otherwise irreversible, unlike Archive, so this is
        intentionally harder to trigger than the plain Action > Delete menu
        (which unlink() above refuses outright).
        """
        self.with_context(ec_delete_password_confirmed=True).unlink()
        # Redirect back to the list instead of ir.actions.act_window_close:
        # this button lives on a full-page form (not a dialog), so closing
        # alone leaves the client trying to reload the now-deleted record.
        return self.env['ir.actions.act_window']._for_xml_id('engineering_change.action_engineering_change_all')

    def write(self, vals):
        keys = set(vals.keys())
        guarded_keys = keys & (self.ENGINEER_FIELDS | self.MANAGER_FIELDS | {'request_type'})
        if guarded_keys:
            for rec in self:
                rec._check_field_edit_permissions(keys)
        workflow_keys = keys & self.WORKFLOW_FIELDS
        if 'dcr_no' in workflow_keys and self.env.user.has_group('engineering_change.group_ec_edit_dcr_no'):
            # Edit DCR Number holders may correct dcr_no directly (e.g. fixing
            # a typo, or a number issued under an old numbering format) -
            # everything else in WORKFLOW_FIELDS still requires going through
            # the workflow buttons below.
            workflow_keys = workflow_keys - {'dcr_no'}
        if workflow_keys and not self.env.context.get('ec_workflow_write'):
            raise UserError(_(
                "%s can only change via the workflow buttons (Submit / Approve / "
                "Reject / Close / Reopen), not by editing the field directly."
            ) % ', '.join(sorted(workflow_keys)))
        if 'active' in keys:
            for rec in self:
                rec._check_archive_permission()
        result = super().write(vals)
        if 'request_type' in keys:
            self._sync_dcr_no_on_type_change()
        return result

    # Once a request already went through BOD approval (state at/after
    # 'implement'), the normal action_bod_approve() flow that assigns
    # dcr_no won't run again - only the Manager/Admin can still flip
    # request_type at that point (see can_edit_request_type), and this
    # keeps dcr_no consistent with the corrected type without requiring a
    # Reject-to-Draft round trip. Earlier states are left alone: dcr_no is
    # still assigned by action_bod_approve() once the request actually
    # reaches BOD approval, same as always.
    def _sync_dcr_no_on_type_change(self):
        for rec in self:
            if rec.request_type == 'dcr' and not rec.dcr_no and rec.state not in ('draft', 'waiting_manager_approval', 'bod_review'):
                rec.with_context(ec_workflow_write=True).dcr_no = rec._next_dcr_no() or False
            elif rec.request_type == 'minor' and rec.dcr_no:
                rec.with_context(ec_workflow_write=True).dcr_no = False

    def _next_dcr_no(self):
        """Next DCR No, formatted yymmDCxx (e.g. 2608DC01) - the 2-digit
        counter resets to 01 every calendar month. ir.sequence's own
        use_date_range only resets yearly (see _create_date_range_seq in
        Odoo core, which always buckets Jan 1 - Dec 31 regardless of what
        date codes the prefix uses), so a monthly reset needs its own
        sequence per year-month instead - created lazily here the first
        time a given month is needed, reusing ir.sequence's atomic
        next_by_code() for the actual counter (safe under concurrent BOD
        approvals) rather than hand-rolling a race-prone max()+1 query.
        """
        self.ensure_one()
        period = fields.Date.context_today(self).strftime('%y%m')
        code = f'engineering.change.dcr.{period}'
        Sequence = self.env['ir.sequence'].sudo()
        number = Sequence.next_by_code(code)
        if number:
            return number
        Sequence.create({
            'name': f'Engineering Change DCR No {period}',
            'code': code,
            'prefix': f'{period}DC',
            'padding': 2,
            'number_increment': 1,
            'implementation': 'standard',
        })
        return Sequence.next_by_code(code)

    def _check_field_edit_permissions(self, keys):
        self.ensure_one()
        user = self.env.user
        is_engineer = user.has_group('engineering_change.group_ec_engineer')
        # Manager Approve and Administrator may always edit any content of the
        # request, regardless of state or role - they're trusted to correct it
        # directly instead of going through the Reject-to-Draft round trip.
        is_manager = user.has_group('engineering_change.group_ec_manager') \
            or user.has_group('base.group_system')
        is_approver = user.has_group('engineering_change.group_ec_bod') or is_manager

        engineer_keys = keys & self.ENGINEER_FIELDS
        if engineer_keys and not is_manager:
            if self.state != 'draft':
                raise UserError(_(
                    "The request content (%s) can only be edited while the request is in Draft. "
                    "Reject it back to Draft first if it needs correction."
                ) % ', '.join(sorted(engineer_keys)))
            if not is_engineer:
                raise AccessError(_("Only the Request role can edit the request content."))

        manager_keys = keys & self.MANAGER_FIELDS
        if manager_keys:
            if not is_approver:
                raise AccessError(_("Only BOD Approve / Manager Approve can edit the Implement Team fields."))
            if self.state == 'done' and not is_manager:
                raise UserError(_("Reopen the request before editing the Implement Team fields."))

        if 'request_type' in keys and not is_manager:
            if not (is_engineer or is_approver):
                raise AccessError(_("Only the Request or Approve roles can change the Request Type."))
            if self.state not in ('draft', 'waiting_manager_approval'):
                raise UserError(_("Request Type can only be changed before it reaches BOD Review / Implement."))
            if is_engineer and not is_approver and self.state != 'draft':
                raise UserError(_("Request Type can only be changed by the Request role while in Draft."))

    def _check_archive_permission(self):
        """Only the request's own Engineer (its creator/owner) or Manager
        Approve may archive/unarchive it - BOD Approve and other Engineers
        otherwise have unconditional base write access to the model, which
        would let them archive any request without this check.
        """
        self.ensure_one()
        user = self.env.user
        is_manager = user.has_group('engineering_change.group_ec_manager')
        if is_manager or self.engineer_id == user:
            return
        raise AccessError(_(
            "Only the request's Engineer or the Manager can archive/unarchive this request."))
