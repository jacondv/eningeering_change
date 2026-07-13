from odoo import _, api, fields, models
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
        'title', 'description', 'engineer_id', 'rpn',
        'impact_lead_time', 'impact_safety', 'impact_compliance',
        'image_ids', 'document_ids',
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
    title = fields.Char(required=True, tracking=True)
    description = fields.Html(required=True, tracking=True)
    engineer_id = fields.Many2one(
        'res.users', string='Engineer', required=True, index=True,
        default=lambda self: self.env.user, tracking=True)
    close_date = fields.Datetime(readonly=True, copy=False)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('waiting_manager_approval', 'Manager Approval'),
        ('bod_review', 'BOD Approval'),
        ('implement', 'Implement'),
        ('production', 'Production'),
        ('done', 'Done'),
    ], default='draft', copy=False, tracking=True, index=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)
    active = fields.Boolean(default=True)

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
    has_overdue_action = fields.Boolean(compute='_compute_has_overdue', store=True)
    next_action_deadline = fields.Date(compute='_compute_next_action_deadline', store=True, string='Next Deadline')

    # UX hints for the view (readonly conditions). The write() guard below is the
    # actual enforcement; these just let the form grey fields out accordingly.
    can_edit_engineer_fields = fields.Boolean(compute='_compute_edit_rights')
    can_edit_manager_fields = fields.Boolean(compute='_compute_edit_rights')
    can_edit_request_type = fields.Boolean(compute='_compute_edit_rights')
    can_confirm_production = fields.Boolean(compute='_compute_edit_rights')

    _rpn_non_negative = models.Constraint(
        'CHECK(rpn >= 0)',
        'RPN cannot be negative.',
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
        is_manager = user.has_group('engineering_change.group_ec_manager')
        is_approver = user.has_group('engineering_change.group_ec_bod') or is_manager
        for rec in self:
            rec.can_edit_engineer_fields = is_engineer and rec.state == 'draft'
            rec.can_edit_manager_fields = is_approver and rec.state != 'done'
            rec.can_edit_request_type = (
                (is_engineer and rec.state == 'draft')
                or (is_approver and rec.state in ('draft', 'waiting_manager_approval'))
            )
            rec.can_confirm_production = is_manager or rec.implement_owner_id == user

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
        for rec in self:
            if rec.state != 'draft' and not (
                self.env.context.get('force_delete') and self.env.user.has_group('engineering_change.group_ec_delete')
            ):
                raise UserError(_("You can only delete a Request that is still in Draft state."))
        return super().unlink()

    def write(self, vals):
        keys = set(vals.keys())
        guarded_keys = keys & (self.ENGINEER_FIELDS | self.MANAGER_FIELDS | {'request_type'})
        if guarded_keys:
            for rec in self:
                rec._check_field_edit_permissions(keys)
        workflow_keys = keys & self.WORKFLOW_FIELDS
        if workflow_keys and not self.env.context.get('ec_workflow_write'):
            raise UserError(_(
                "%s can only change via the workflow buttons (Submit / Approve / "
                "Reject / Close / Reopen), not by editing the field directly."
            ) % ', '.join(sorted(workflow_keys)))
        if 'active' in keys:
            for rec in self:
                rec._check_archive_permission()
        return super().write(vals)

    def _check_field_edit_permissions(self, keys):
        self.ensure_one()
        user = self.env.user
        is_engineer = user.has_group('engineering_change.group_ec_engineer')
        is_approver = user.has_group('engineering_change.group_ec_bod') \
            or user.has_group('engineering_change.group_ec_manager')

        engineer_keys = keys & self.ENGINEER_FIELDS
        if engineer_keys:
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
            if self.state == 'done':
                raise UserError(_("Reopen the request before editing the Implement Team fields."))

        if 'request_type' in keys:
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
