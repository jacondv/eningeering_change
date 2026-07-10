from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


class EngineeringChange(models.Model):
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

    @api.constrains('implement_owner_id', 'implement_team_ids')
    def _check_implement_owner(self):
        for rec in self:
            if rec.implement_owner_id and rec.implement_owner_id not in rec.implement_team_ids:
                raise ValidationError(_("Implement Owner must be a member of the Implement Team."))

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

    # ------------------------------------------------------------
    # Notification helpers
    # ------------------------------------------------------------
    def _get_group_partners(self, group_xmlid):
        group = self.env.ref(group_xmlid, raise_if_not_found=False)
        return group.user_ids.mapped('partner_id') if group else self.env['res.partner']

    def _send_template(self, template_xmlid, partners=None):
        self.ensure_one()
        template = self.env.ref(template_xmlid, raise_if_not_found=False)
        if not template:
            return
        email_values = {'recipient_ids': [(6, 0, partners.ids)]} if partners else {}
        template.send_mail(self.id, force_send=False, email_values=email_values)

    def _notify_implement_team(self, template_xmlid, body=None):
        for rec in self:
            partners = rec.implement_team_ids.mapped('partner_id')
            if partners:
                rec.message_subscribe(partner_ids=partners.ids)
            rec._send_template(template_xmlid, partners=partners)
            if body:
                rec.message_post(body=body, partner_ids=partners.ids)

    # ------------------------------------------------------------
    # Workflow
    # ------------------------------------------------------------
    def action_submit(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_("Only Draft requests can be submitted."))
            if not rec.title or not rec.description or rec.rpn <= 0:
                raise UserError(_(
                    "Title, Description and a valid RPN (greater than 0) are required before submitting."))
            if rec.name == 'New':
                rec.name = self.env['ir.sequence'].next_by_code('engineering.change') or 'New'
            rec.with_context(ec_workflow_write=True).state = 'waiting_manager_approval'
            partners = rec._get_group_partners('engineering_change.group_ec_manager')
            if partners:
                rec.message_subscribe(partner_ids=partners.ids)
            rec._send_template('engineering_change.mail_template_submit', partners=partners)
            rec.message_post(
                body=_("Request submitted for Manager approval."), partner_ids=partners.ids)

    def action_manager_approve(self):
        for rec in self:
            if rec.state != 'waiting_manager_approval':
                raise UserError(_("Only requests waiting for Manager approval can be approved."))
            if rec.request_type == 'dcr':
                rec.with_context(ec_workflow_write=True).state = 'bod_review'
                partners = rec._get_group_partners('engineering_change.group_ec_bod')
                if partners:
                    rec.message_subscribe(partner_ids=partners.ids)
                rec._send_template('engineering_change.mail_template_bod_review', partners=partners)
                rec.message_post(
                    body=_("Approved by Manager, forwarded to BOD for review."),
                    partner_ids=partners.ids)
            else:
                rec.with_context(ec_workflow_write=True).state = 'implement'
                rec._notify_implement_team(
                    'engineering_change.mail_template_implement',
                    body=_("Approved by Manager. Moved to Implementation."))

    def action_bod_approve(self):
        for rec in self:
            if rec.state != 'bod_review':
                raise UserError(_("Only requests in BOD Review can be approved by BOD."))
            if not rec.implement_team_ids:
                raise UserError(_("Implement Team cannot be empty before BOD approval."))
            rec.with_context(ec_workflow_write=True).write({
                'bod_approver_id': self.env.user.id,
                'dcr_no': rec.dcr_no or self.env['ir.sequence'].next_by_code('engineering.change.dcr') or False,
                'state': 'implement',
            })
            rec._notify_implement_team(
                'engineering_change.mail_template_implement',
                body=_("Approved by BOD (%s). Moved to Implementation.") % self.env.user.name)

    def _apply_reject(self, reason, reject_by):
        self.ensure_one()
        self.with_context(ec_workflow_write=True).write({'state': 'draft', 'reject_reason': reason})
        partners = self.engineer_id.partner_id
        template_xmlid = (
            'engineering_change.mail_template_bod_reject' if reject_by == 'bod'
            else 'engineering_change.mail_template_manager_reject'
        )
        if partners:
            self.message_subscribe(partner_ids=partners.ids)
        self._send_template(template_xmlid, partners=partners)
        self.message_post(
            body=_("Request rejected. Reason: %s") % reason, partner_ids=partners.ids)

    def action_confirm_production(self):
        for rec in self:
            if rec.state != 'implement':
                raise UserError(_("Only requests in Implement state can move to Production."))
            if not rec.can_confirm_production:
                raise AccessError(_(
                    "Only the Manager or the request's Implement Owner can confirm Production."))
            # sudo(): the Implement Owner allowed through the check above is not
            # necessarily an Engineer/BOD/Manager Approve holder with base write
            # access on engineering.change (e.g. a plain team member) - the
            # can_confirm_production check just above is the real gate.
            rec_sudo = rec.sudo()
            rec_sudo.with_context(ec_workflow_write=True).state = 'production'
            partners = (rec.engineer_id | rec.implement_team_ids).mapped('partner_id')
            if partners:
                rec_sudo.message_subscribe(partner_ids=partners.ids)
            rec_sudo.message_post(
                body=_("Moved to Production, confirmed by %s.") % self.env.user.name,
                partner_ids=partners.ids)

    def _previous_workflow_state(self):
        """The state right before the current one in the normal forward flow,
        used by action_revert_to_previous_state to undo an accidental click.
        Not defined for 'draft' (nothing before it) or 'done' (Reopen already
        owns that specific transition, with its own dedicated button/label).
        """
        self.ensure_one()
        if self.state == 'waiting_manager_approval':
            return 'draft'
        if self.state == 'bod_review':
            return 'waiting_manager_approval'
        if self.state == 'implement':
            return 'bod_review' if self.request_type == 'dcr' else 'waiting_manager_approval'
        if self.state == 'production':
            return 'implement'
        return False

    def action_revert_to_previous_state(self):
        """Manager-only safety valve to undo an accidental workflow click
        (e.g. Confirm Production hit by mistake) by stepping back exactly one
        state, without going through the Reject wizard (which always resets
        all the way to Draft and requires a reason).
        """
        state_labels = dict(self._fields['state'].selection)
        for rec in self:
            if not self.env.user.has_group('engineering_change.group_ec_manager'):
                raise UserError(_("Only Engineering Manager can revert a request to its previous state."))
            previous_state = rec._previous_workflow_state()
            if not previous_state:
                raise UserError(_("This request has no previous state to revert to."))
            from_label = state_labels[rec.state]
            rec.with_context(ec_workflow_write=True).state = previous_state
            partners = (rec.engineer_id | rec.implement_team_ids).mapped('partner_id')
            rec.message_post(
                body=_("Reverted from %(from_state)s back to %(to_state)s by %(user)s.") % {
                    'from_state': from_label,
                    'to_state': state_labels[previous_state],
                    'user': self.env.user.name,
                },
                partner_ids=partners.ids)

    def action_close_request(self):
        for rec in self:
            if rec.state != 'production':
                raise UserError(_("Only requests in Production state can be closed."))
            if not self.env.user.has_group('engineering_change.group_ec_manager'):
                raise UserError(_("Only Engineering Manager can close a request."))
            rec.with_context(ec_workflow_write=True).write(
                {'state': 'done', 'close_date': fields.Datetime.now()})
            partners = (rec.engineer_id | rec.implement_team_ids).mapped('partner_id')
            if partners:
                rec.message_subscribe(partner_ids=partners.ids)
            rec.message_post(body=_("Request closed."), partner_ids=partners.ids)

    def action_reopen(self):
        for rec in self:
            if not self.env.user.has_group('engineering_change.group_ec_manager'):
                raise UserError(_("Only Engineering Manager can reopen a request."))
            if rec.state != 'done':
                raise UserError(_("Only Done requests can be reopened."))
            rec.with_context(ec_workflow_write=True).write(
                {'state': 'production', 'close_date': False})
            partners = (rec.engineer_id | rec.implement_team_ids).mapped('partner_id')
            rec.message_post(
                body=_("Request reopened by %s.") % self.env.user.name, partner_ids=partners.ids)

    def action_view_actions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Actions'),
            'res_model': 'project.task',
            'view_mode': 'list,form',
            'views': [
                (self.env.ref('engineering_change.view_engineering_change_action_list').id, 'list'),
                (self.env.ref('engineering_change.view_engineering_change_action_form').id, 'form'),
            ],
            'domain': [('change_id', '=', self.id)],
            'context': {'default_change_id': self.id},
        }

    def action_view_evidence(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Evidence'),
            'res_model': 'engineering.change.action.evidence',
            'view_mode': 'list,form',
            'views': [
                (self.env.ref('engineering_change.view_engineering_change_action_evidence_list').id, 'list'),
                (self.env.ref('engineering_change.view_engineering_change_action_evidence_form').id, 'form'),
            ],
            'domain': [('task_id.change_id', '=', self.id)],
        }

    def action_open_reject_wizard(self, reject_by):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Reject Request'),
            'res_model': 'engineering.change.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_change_id': self.id,
                'default_reject_by': reject_by,
            },
        }

    def action_manager_reject(self):
        self.ensure_one()
        return self.action_open_reject_wizard('manager')

    def action_bod_reject(self):
        self.ensure_one()
        return self.action_open_reject_wizard('bod')

    # ------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------
    @api.model
    def get_dashboard_data(self):
        """Aggregate stats for the Dashboard client action. Uses search_read +
        Python aggregation (instead of read_group) since dataset sizes here are
        small and it sidesteps any read_group API differences in this build.
        Respects ir.rule like any other read, so every role sees the same
        totals (matches the "everyone can view everything" design).
        """
        Change = self.env['engineering.change']
        Task = self.env['project.task']

        changes = Change.search_read(
            [], ['state', 'request_type', 'rpn_level', 'has_overdue_action'])
        state_selection = Change._fields['state'].selection
        type_selection = Change._fields['request_type'].selection
        rpn_selection = Change._fields['rpn_level'].selection

        state_counts = {key: 0 for key, _label in state_selection}
        type_counts = {key: 0 for key, _label in type_selection}
        rpn_counts = {key: 0 for key, _label in rpn_selection}
        overdue_requests = 0
        for c in changes:
            state_counts[c['state']] = state_counts.get(c['state'], 0) + 1
            type_counts[c['request_type']] = type_counts.get(c['request_type'], 0) + 1
            if c['rpn_level']:
                rpn_counts[c['rpn_level']] = rpn_counts.get(c['rpn_level'], 0) + 1
            if c['has_overdue_action']:
                overdue_requests += 1

        tasks = Task.search_read([('change_id', '!=', False)], ['state', 'is_overdue'])
        task_state_selection = Task._fields['state'].selection
        task_state_counts = {key: 0 for key, _label in task_state_selection}
        overdue_tasks = 0
        done_tasks = 0
        for t in tasks:
            task_state_counts[t['state']] = task_state_counts.get(t['state'], 0) + 1
            if t['is_overdue']:
                overdue_tasks += 1
            if t['state'] == '1_done':
                done_tasks += 1
        total_tasks = len(tasks)
        task_progress = round(done_tasks / total_tasks * 100, 1) if total_tasks else 0.0

        recent_requests = Change.search_read(
            [], ['name', 'title', 'state', 'request_type', 'engineer_id'],
            order='create_date desc', limit=8)

        my_open_tasks = Task.search_read(
            [
                ('change_id', '!=', False),
                ('user_ids', 'in', [self.env.user.id]),
                ('state', 'not in', ['1_done', '1_canceled']),
            ],
            ['name', 'change_id', 'date_deadline', 'is_overdue'],
            order='date_deadline asc', limit=8)

        return {
            'total_requests': len(changes),
            'state_counts': [
                {'key': k, 'label': label, 'count': state_counts.get(k, 0)}
                for k, label in state_selection
            ],
            'type_counts': [
                {'key': k, 'label': label, 'count': type_counts.get(k, 0)}
                for k, label in type_selection
            ],
            'rpn_counts': [
                {'key': k, 'label': label, 'count': rpn_counts.get(k, 0)}
                for k, label in rpn_selection
            ],
            'overdue_requests': overdue_requests,
            'total_tasks': total_tasks,
            'done_tasks': done_tasks,
            'overdue_tasks': overdue_tasks,
            'task_progress': task_progress,
            'task_state_counts': [
                {'key': k, 'label': label, 'count': task_state_counts.get(k, 0)}
                for k, label in task_state_selection
            ],
            'recent_requests': recent_requests,
            'my_open_tasks': my_open_tasks,
        }

    @api.model
    def get_ec_task_action(self, domain=None, res_id=None):
        """Build an act_window action on project.task using this addon's own
        Task list/form views (same ones the Actions/Tasks menu uses) rather
        than core Project's default views. Used by the Dashboard client
        action so its links open the same views/columns a user would get by
        clicking through the actual menu, without depending on the search
        view's default filters (which shouldn't apply to a dashboard link
        that's already about one specific status/record).
        """
        action = {
            'type': 'ir.actions.act_window',
            'name': _('Actions / Tasks'),
            'res_model': 'project.task',
            'views': [
                (self.env.ref('engineering_change.view_engineering_change_action_list').id, 'list'),
                (self.env.ref('engineering_change.view_engineering_change_action_form').id, 'form'),
            ],
            'domain': domain or [('change_id', '!=', False)],
        }
        if res_id:
            action['res_id'] = res_id
            action['view_mode'] = 'form'
        return action
