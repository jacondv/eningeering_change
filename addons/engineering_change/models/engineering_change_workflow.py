from odoo import _, fields, models
from odoo.exceptions import AccessError, UserError


class EngineeringChange(models.Model):
    """The request's state machine (Submit / Approve / Reject / Confirm
    Sales / Close / Reopen / Revert) and the notification helpers it
    uses. Split out from engineering_change.py, which owns the record's
    fields, computed UX hints, and field-level edit guards - this file only
    ever changes `state` (and its side-effect fields) through the workflow
    methods below, never through a bare write().
    """
    _inherit = 'engineering.change'

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
            if not rec.title or not rec.description or not rec.change_category:
                raise UserError(_(
                    "Title, Description and Change Category are required before submitting."))
            if rec.name == 'New':
                rec.name = self.env['ir.sequence'].next_by_code('engineering.change') or 'New'
            if not rec.project_id:
                rec._link_ec_project()
            rec.with_context(ec_workflow_write=True).state = 'waiting_manager_approval'
            partners = rec._get_group_partners('engineering_change.group_ec_manager')
            if partners:
                rec.message_subscribe(partner_ids=partners.ids)
            # No email on Submit (per request) - still logged to chatter/inbox
            # below, so Line Manager still sees it without an outgoing email.
            rec.message_post(
                body=_("Request submitted for Manager approval."), partner_ids=partners.ids)

    def _get_direct_manager_user(self):
        """The res.users who is this request's Engineer's direct manager, via
        hr.employee.parent_id -> the parent employee's own user_id. Returns
        False if the Engineer has no hr.employee record, or has one but no
        manager assigned on it - callers treat False as "not enough HR data
        to restrict, let any Line Manager approve" (see _apply_approve).
        """
        self.ensure_one()
        employee = self.env['hr.employee'].sudo().search(
            [('user_id', '=', self.engineer_id.id)], limit=1)
        if not employee or not employee.parent_id or not employee.parent_id.user_id:
            return False
        return employee.parent_id.user_id

    def _apply_approve(self, note, approve_by):
        """Runs the actual Line Manager/Head Manager/BOC approval side effects
        (called by the Approve wizard) and logs the decision to
        approval_log_ids. Comment is optional on Approve (unlike Reject,
        which always requires a reason).
        """
        self.ensure_one()
        if approve_by == 'manager':
            if self.state != 'waiting_manager_approval':
                raise UserError(_("Only requests waiting for Line Manager approval can be approved."))
            direct_manager = self._get_direct_manager_user()
            if (direct_manager and self.env.user != direct_manager
                    and not self.env.user.has_group('base.group_system')):
                raise AccessError(_(
                    "Only %s, this Engineer's direct Line Manager (set on their "
                    "Employee record), can approve this request."
                ) % direct_manager.name)
            self.with_context(ec_workflow_write=True).state = 'waiting_head_office_approval'
            partners = self._get_group_partners('engineering_change.group_ec_head_office')
            if partners:
                self.message_subscribe(partner_ids=partners.ids)
            self._send_template('engineering_change.mail_template_head_office_review', partners=partners)
            self.message_post(
                body=_("Approved by Line Manager, forwarded to Head Manager for review."),
                partner_ids=partners.ids)
        elif approve_by == 'head_office':
            if self.state != 'waiting_head_office_approval':
                raise UserError(_("Only requests waiting for Head Manager approval can be approved."))
            if self.request_type == 'dcr':
                self.with_context(ec_workflow_write=True).state = 'bod_review'
                partners = self._get_group_partners('engineering_change.group_ec_bod')
                if partners:
                    self.message_subscribe(partner_ids=partners.ids)
                self._send_template('engineering_change.mail_template_bod_review', partners=partners)
                self.message_post(
                    body=_("Approved by Head Manager, forwarded to BOC for review."),
                    partner_ids=partners.ids)
            else:
                self.with_context(ec_workflow_write=True).state = 'implement'
                self._notify_implement_team(
                    'engineering_change.mail_template_implement',
                    body=_("Approved by Head Manager. Moved to Implementation."))
        else:
            if self.state != 'bod_review':
                raise UserError(_("Only requests in BOC Approval can be approved by BOC."))
            if not self.implement_team_ids:
                raise UserError(_("Implement Team cannot be empty before BOC approval."))
            self.with_context(ec_workflow_write=True).write({
                'bod_approver_id': self.env.user.id,
                'dcr_no': self.dcr_no or self._next_dcr_no() or False,
                'state': 'implement',
            })
            self._notify_implement_team(
                'engineering_change.mail_template_implement',
                body=_("Approved by BOC (%s). Moved to Implementation.") % self.env.user.name)
        self.env['engineering.change.approval.log'].create({
            'change_id': self.id,
            'role': approve_by,
            'decision': 'approved',
            'note': note or '',
        })

    def _apply_reject(self, reason, reject_by, outcome='draft'):
        """outcome='draft' (default) is the original behavior: back to Draft
        for editing and resubmitting. outcome='cancel' is the dead-end exit
        instead - state becomes 'canceled' (shown as "Rejected" - see the
        Selection label on `state`), which also drops it out of the
        default All/My Requests list (the "Rejected" search filter brings
        it back). Both still log an approval_log_ids row and notify the
        Engineer the same way - a full cancel is still a rejection from
        their point of view, just one with no way back to Draft.
        """
        self.ensure_one()
        target_state = 'canceled' if outcome == 'cancel' else 'draft'
        self.with_context(ec_workflow_write=True).write({'state': target_state, 'reject_reason': reason})
        self.env['engineering.change.approval.log'].create({
            'change_id': self.id,
            'role': reject_by,
            'decision': 'rejected',
            'note': reason,
        })
        partners = self.engineer_id.partner_id
        template_xmlid = {
            'bod': 'engineering_change.mail_template_bod_reject',
            'head_office': 'engineering_change.mail_template_head_office_reject',
            'manager': 'engineering_change.mail_template_manager_reject',
        }[reject_by]
        if partners:
            self.message_subscribe(partner_ids=partners.ids)
        self._send_template(template_xmlid, partners=partners)
        body = (_("Request rejected and moved back to Draft. Reason: %s") % reason if outcome == 'draft'
                else _("Request rejected and canceled. Reason: %s") % reason)
        self.message_post(body=body, partner_ids=partners.ids)

    def action_confirm_production(self):
        for rec in self:
            if rec.state != 'implement':
                raise UserError(_("Only requests in Design state can move to Production."))
            if not rec.can_confirm_production:
                raise AccessError(_(
                    "Only the Manager or the request's Implement Owner can confirm Production."))
            # sudo(): the Implement Owner allowed through the check above is not
            # necessarily an Engineer/BOC/Manager Approve holder with base write
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

    def action_confirm_sale(self):
        for rec in self:
            if rec.state != 'production':
                raise UserError(_("Only requests in Production state can move to Sales."))
            if not rec.can_confirm_sale:
                raise AccessError(_(
                    "Only the Manager or the request's Implement Owner can confirm Sales."))
            # sudo(): the Implement Owner allowed through the check above is not
            # necessarily an Engineer/BOC/Manager Approve holder with base write
            # access on engineering.change (e.g. a plain team member) - the
            # can_confirm_sale check just above is the real gate.
            rec_sudo = rec.sudo()
            rec_sudo.with_context(ec_workflow_write=True).state = 'sale'
            partners = (rec.engineer_id | rec.implement_team_ids).mapped('partner_id')
            if partners:
                rec_sudo.message_subscribe(partner_ids=partners.ids)
            rec_sudo.message_post(
                body=_("Moved to Sales, confirmed by %s.") % self.env.user.name,
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
        if self.state == 'waiting_head_office_approval':
            return 'waiting_manager_approval'
        if self.state == 'bod_review':
            return 'waiting_head_office_approval'
        if self.state == 'implement':
            return 'bod_review' if self.request_type == 'dcr' else 'waiting_head_office_approval'
        if self.state == 'production':
            return 'implement'
        if self.state == 'sale':
            return 'production'
        return False

    def action_revert_to_previous_state(self):
        """Manager-only safety valve to undo an accidental workflow click
        (e.g. Confirm Sale hit by mistake) by stepping back exactly one
        state, without going through the Reject wizard (which always resets
        all the way to Draft and requires a reason).
        """
        state_labels = dict(self._fields['state'].selection)
        for rec in self:
            if not self.env.user.has_group('engineering_change.group_ec_manager'):
                raise UserError(_("Only Line Manager can revert a request to its previous state."))
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
            if rec.state != 'sale':
                raise UserError(_("Only requests in Sales state can be closed."))
            if not (self.env.user.has_group('engineering_change.group_ec_manager')
                    or self.env.user.has_group('engineering_change.group_ec_close')):
                raise UserError(_("Only Line Manager or a user granted Close rights can close a request."))
            # sudo(): a Close-group-only user's write access is scoped to
            # state == 'sale' (see ec_change_rule_close_write) - once the
            # state flips to 'done' below, they'd lose write access to their own
            # just-closed record for the chatter side effects that follow.
            rec_sudo = rec.sudo()
            rec_sudo.with_context(ec_workflow_write=True).write(
                {'state': 'done', 'close_date': fields.Datetime.now()})
            partners = (rec.engineer_id | rec.implement_team_ids).mapped('partner_id')
            if partners:
                rec_sudo.message_subscribe(partner_ids=partners.ids)
            rec_sudo.message_post(body=_("Request closed."), partner_ids=partners.ids)

    def action_reopen(self):
        for rec in self:
            if not self.env.user.has_group('engineering_change.group_ec_manager'):
                raise UserError(_("Only Line Manager can reopen a request."))
            if rec.state != 'done':
                raise UserError(_("Only Done requests can be reopened."))
            rec.with_context(ec_workflow_write=True).write(
                {'state': 'sale', 'close_date': False})
            partners = (rec.engineer_id | rec.implement_team_ids).mapped('partner_id')
            rec.message_post(
                body=_("Request reopened by %s.") % self.env.user.name, partner_ids=partners.ids)

    # ------------------------------------------------------------
    # Reject wizard glue
    # ------------------------------------------------------------
    def _current_reject_role(self):
        """Which role is doing the reject, for approval_log_ids/the reject
        email template - derived from the current user's own groups rather
        than a fixed per-button value, since Reject is now a single,
        stage-agnostic button (see can_reject) instead of one button per
        role/stage. group_ec_head_office implies group_ec_manager, so it's
        checked first - otherwise a Head Manager would always be logged as
        plain 'manager'."""
        self.ensure_one()
        user = self.env.user
        if self.state == 'bod_review' and user.has_group('engineering_change.group_ec_bod'):
            return 'bod'
        if user.has_group('engineering_change.group_ec_head_office'):
            return 'head_office'
        return 'manager'

    def action_open_reject_wizard(self):
        self.ensure_one()
        if not self.can_reject:
            raise AccessError(_("You are not allowed to reject this request at its current stage."))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Reject Request'),
            'res_model': 'engineering.change.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_change_id': self.id,
                'default_reject_by': self._current_reject_role(),
            },
        }

    # ------------------------------------------------------------
    # Approve wizard glue
    # ------------------------------------------------------------
    def action_open_approve_wizard(self, approve_by):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Approve Request'),
            'res_model': 'engineering.change.approve.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_change_id': self.id,
                'default_approve_by': approve_by,
            },
        }

    def action_manager_approve(self):
        self.ensure_one()
        return self.action_open_approve_wizard('manager')

    def action_head_office_approve(self):
        self.ensure_one()
        return self.action_open_approve_wizard('head_office')

    def action_bod_approve(self):
        self.ensure_one()
        return self.action_open_approve_wizard('bod')

    # ------------------------------------------------------------
    # Recall (self-service undo of one's own Approve)
    # ------------------------------------------------------------
    def action_recall_approval(self):
        """Lets Line Manager or Head Manager pull their own Approve back by
        exactly one step, or lets the Engineer pull their own Submit back to
        Draft, without going through the Reject wizard (which always resets
        to Draft and requires a reason). Only reachable while the next stage
        hasn't approved/acted yet - once it has, the state has already moved
        past the recallable window, so the button's own invisible condition
        (tied to the current state) naturally disables it.
        """
        self.ensure_one()
        user = self.env.user
        is_admin = user.has_group('base.group_system')
        is_manager = user.has_group('engineering_change.group_ec_manager')
        is_head_office = user.has_group('engineering_change.group_ec_head_office')
        if self.state == 'waiting_manager_approval' and (is_admin or self.engineer_id == user):
            target_state = 'draft'
        elif self.state == 'waiting_head_office_approval' and is_manager:
            target_state = 'waiting_manager_approval'
        elif self.state == 'bod_review' and is_head_office:
            target_state = 'waiting_head_office_approval'
        else:
            raise UserError(_("You cannot recall approval at the current stage."))
        state_labels = dict(self._fields['state'].selection)
        from_label = state_labels[self.state]
        # sudo(): the Engineer allowed through the first branch above (self.engineer_id
        # == user) is not necessarily a group_ec_engineer holder with base write access
        # on engineering.change (e.g. engineer_id was reassigned to a plain viewer) -
        # the checks above are the real gate, same reasoning as action_confirm_production.
        self.sudo().with_context(ec_workflow_write=True).state = target_state
        self.message_post(
            body=_("Approval recalled by %(user)s: sent back from %(from_state)s to %(to_state)s.") % {
                'user': user.name,
                'from_state': from_label,
                'to_state': state_labels[target_state],
            })
