from odoo import _, fields, models
from odoo.exceptions import AccessError, UserError


class EngineeringChange(models.Model):
    """The request's state machine (Submit / Approve / Reject / Confirm
    Production / Confirm Sale / Close / Reopen / Recall) and the
    notification helpers it uses. Split out from engineering_change.py,
    which owns the record's fields, computed UX hints, and field-level edit
    guards - this file only ever changes `state` (and its side-effect
    fields) through the workflow methods below, never through a bare
    write().
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

    def _notify(self, partners, body):
        """Subscribe `partners` (if any) and post `body` to Chatter -
        the subscribe-then-post pair every workflow transition below ends
        with, collapsed into one call so the "if partners" guard can't be
        forgotten in a new one. No mail template/outgoing email here - use
        _send_template first for that (see _apply_reject, the only
        remaining caller - Approve no longer sends an email, per request).
        """
        self.ensure_one()
        if partners:
            self.message_subscribe(partner_ids=partners.ids)
        self.message_post(body=body, partner_ids=partners.ids)

    def _state_labels(self):
        return dict(self._fields['state'].selection)

    # ------------------------------------------------------------
    # Workflow
    # ------------------------------------------------------------
    # Change Source values exempt from the Impact Analysis gate below - a
    # Client Feedback/Product Support request can Submit without answering
    # any of the 4 Impact Analysis questions, and always ends up DCR (see
    # _apply_approve's manager branch). change_category's own technical
    # value for the latter is the oddly-capitalized 'Product Support' (see
    # its Selection definition in engineering_change.py) - kept as-is here
    # rather than renamed, to avoid a data migration on existing records.
    IMPACT_GATE_EXEMPT_CATEGORIES = ('client_feedback', 'Product Support')

    def _impact_gate_missing_fields(self):
        """Returns the list of Impact Analysis field names still unanswered
        that block Submit - empty if this request is exempt (see
        IMPACT_GATE_EXEMPT_CATEGORIES) or already has everything it needs:
        impact_negative always required, the other 3 only when
        impact_negative == 'no'. Doesn't flag impact_negative == 'yes' as
        needing more - that's allowed to reach Submit and is instead
        auto-rejected right after (see _auto_reject_negative_impact), so the
        "Yes" answer and its consequence both end up on record with a
        Request No/Chatter trail, not silently blocked. A non-empty result
        pops the answer wizard instead of submitting (see action_submit/
        _open_impact_answer_wizard) rather than raising a plain error.
        """
        self.ensure_one()
        if self.change_category in self.IMPACT_GATE_EXEMPT_CATEGORIES:
            return []
        if not self.impact_negative:
            return ['impact_negative']
        if self.impact_negative == 'no':
            return [f for f in (
                'impact_cost_over_100', 'impact_lead_time_over_week', 'impact_circuit_change',
            ) if not self[f]]
        return []

    def _auto_reject_negative_impact(self):
        """Auto-Reject (outcome='cancel', a dead end - see _apply_reject) right
        after Submit when Impact Analysis' first question was answered Yes
        and the Change Source isn't exempt (see _impact_gate_missing_fields/
        IMPACT_GATE_EXEMPT_CATEGORIES) - no human approver decision involved,
        so this logs directly to approval_log_ids (role='system') instead of
        going through _apply_reject, whose role-to-mail-template map only
        knows the 3 human roles.
        """
        self.ensure_one()
        reason = _("Auto-rejected: 'negative impact, safety or compliance issue' was answered Yes.")
        self.with_context(ec_workflow_write=True).write({'state': 'canceled', 'reject_reason': reason})
        # sudo(): triggered by whoever clicked Submit (normally the Engineer),
        # who isn't necessarily Line Manager/BOC Approve - the only 2 groups
        # granted create on engineering.change.approval.log (see its
        # ir.model.access.csv). This row logs a system decision, not one made
        # by the submitter, so it's correct for it to write regardless of
        # their own approval_log_ids rights.
        self.env['engineering.change.approval.log'].sudo().create({
            'change_id': self.id,
            'role': 'system',
            'decision': 'rejected',
            'note': reason,
        })
        self._notify(self.engineer_id.partner_id, reason)

    def action_submit(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_("Only Draft requests can be submitted."))
            if not rec.title or not rec.description or not rec.change_category:
                raise UserError(_(
                    "Title, Description and Change Category are required before submitting."))
            if rec._impact_gate_missing_fields():
                # Only meaningful for a single record (the form's own Submit
                # button) - popping a wizard mid-loop over several records
                # wouldn't make sense, but Submit is never called that way.
                return rec._open_impact_answer_wizard()
            rec._do_submit()

    def _do_submit(self):
        """The actual Draft -> waiting_manager_approval transition, split out
        of action_submit so the impact-answer wizard's Confirm button (see
        engineering_change_impact_answer_wizard.py) can re-enter here once
        the Impact Analysis gate has already been satisfied, without
        re-running the earlier state/required-field checks a second time.
        """
        self.ensure_one()
        if self.name == 'New':
            self.name = self.env['ir.sequence'].next_by_code('engineering.change') or 'New'
        if not self.project_id:
            self._link_ec_project()
        # Client Feedback/Product Support is always DCR - classified right
        # here on Submit rather than waiting for Line Manager approval (see
        # IMPACT_GATE_EXEMPT_CATEGORIES); everything else still gets
        # classified at approval time instead, once the Impact Analysis
        # answers are on record (see _apply_approve's manager branch).
        if self.change_category in self.IMPACT_GATE_EXEMPT_CATEGORIES:
            self.with_context(ec_workflow_write=True).request_type = 'dcr'
        self.with_context(ec_workflow_write=True).state = 'waiting_manager_approval'
        partners = self._get_group_partners('engineering_change.group_ec_manager')
        # No email on Submit (per request) - still logged to chatter/inbox
        # via _notify, so Line Manager still sees it without an outgoing email.
        self._notify(partners, _("Request submitted for Manager approval."))
        if (self.change_category not in self.IMPACT_GATE_EXEMPT_CATEGORIES
                and self.impact_negative == 'yes'):
            self._auto_reject_negative_impact()

    def _open_impact_answer_wizard(self):
        """Pops the Impact Analysis answer wizard instead of submitting -
        see _impact_gate_missing_fields/action_submit. Pre-fills from
        whatever's already on the record (the object-button's implicit save
        already persisted the in-progress form values), so any question the
        user did answer isn't asked again.
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Answer Impact Analysis Questions'),
            'res_model': 'engineering.change.impact.answer.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_change_id': self.id,
                'default_impact_negative': self.impact_negative,
                'default_impact_cost_over_100': self.impact_cost_over_100,
                'default_impact_lead_time_over_week': self.impact_lead_time_over_week,
                'default_impact_circuit_change': self.impact_circuit_change,
            },
        }

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
            # Auto-classify Minor Change vs DCR right here, on Line Manager
            # approval - re-evaluated unconditionally (not skipped for
            # Client Feedback/Product Support, even though _do_submit already
            # classified those DCR at Submit) because change_category is in
            # ENGINEER_FIELDS, which the Manager can still edit during their
            # own stage (can_edit_engineer_fields is True at
            # waiting_manager_approval) - if they change it, this must
            # re-classify off the CURRENT change_category/impact answers, or
            # Submit's one-time classification would go stale. Still just the
            # classification (request_type) - the DCR number itself
            # (dcr_no) isn't generated until BOC approval, same as before.
            if self.change_category in self.IMPACT_GATE_EXEMPT_CATEGORIES:
                request_type = 'dcr'
            else:
                is_dcr = any(self[f] == 'yes' for f in (
                    'impact_cost_over_100', 'impact_lead_time_over_week', 'impact_circuit_change'))
                request_type = 'dcr' if is_dcr else 'minor'
            self.with_context(ec_workflow_write=True).request_type = request_type
            self.with_context(ec_workflow_write=True).state = 'waiting_head_office_approval'
            partners = self._get_group_partners('engineering_change.group_ec_head_office')
            # No email on Approve (per request) - still logged to chatter/inbox
            # via _notify, same as Submit above.
            self._notify(partners, _("Approved by Line Manager, forwarded to Head Manager for review."))
        elif approve_by == 'head_office':
            if self.state != 'waiting_head_office_approval':
                raise UserError(_("Only requests waiting for Head Manager approval can be approved."))
            if self.request_type == 'dcr':
                self.with_context(ec_workflow_write=True).state = 'bod_review'
                partners = self._get_group_partners('engineering_change.group_ec_bod')
                self._notify(partners, _("Approved by Head Manager, forwarded to BOC for review."))
            else:
                self.with_context(ec_workflow_write=True).state = 'implement'
                self._notify(
                    self.implement_team_ids.mapped('partner_id'),
                    _("Approved by Head Manager. Moved to Implementation."))
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
            self._notify(
                self.implement_team_ids.mapped('partner_id'),
                _("Approved by BOC (%s). Moved to Implementation.") % self.env.user.name)
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
        # .get(), not [reject_by]: an unrecognized reject_by shouldn't crash
        # the whole rejection over a missing email template - it just skips
        # the outgoing email and still logs/notifies via Chatter below.
        template_xmlid = {
            'bod': 'engineering_change.mail_template_bod_reject',
            'head_office': 'engineering_change.mail_template_head_office_reject',
            'manager': 'engineering_change.mail_template_manager_reject',
        }.get(reject_by)
        if template_xmlid:
            self._send_template(template_xmlid, partners=partners)
        body = (_("Request rejected and moved back to Draft. Reason: %s") % reason if outcome == 'draft'
                else _("Request rejected and canceled. Reason: %s") % reason)
        self._notify(partners, body)

    def _confirm_stage(self, from_state, to_state, can_confirm_flag, body):
        """Shared body of action_confirm_production/action_confirm_sale -
        identical except for which state they move from/to, which
        can_confirm_* flag gates them, and their Chatter message.
        """
        for rec in self:
            if rec.state != from_state:
                raise UserError(_(
                    "Only requests in %s state can move to %s."
                ) % (rec._state_labels()[from_state], rec._state_labels()[to_state]))
            if not rec[can_confirm_flag]:
                raise AccessError(_(
                    "Only the Manager or the request's Implement Owner can confirm %s."
                ) % rec._state_labels()[to_state])
            # sudo(): the Implement Owner allowed through the check above is not
            # necessarily an Engineer/BOC/Manager Approve holder with base write
            # access on engineering.change (e.g. a plain team member) - the
            # can_confirm_flag check just above is the real gate.
            rec_sudo = rec.sudo()
            rec_sudo.with_context(ec_workflow_write=True).state = to_state
            partners = (rec.engineer_id | rec.implement_team_ids).mapped('partner_id')
            rec_sudo._notify(partners, body % self.env.user.name)

    def action_confirm_production(self):
        self._confirm_stage(
            'implement', 'production', 'can_confirm_production',
            _("Moved to Production, confirmed by %s."))

    def action_confirm_sale(self):
        self._confirm_stage(
            'production', 'sale', 'can_confirm_sale',
            _("Moved to Sales, confirmed by %s."))

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
            rec_sudo._notify(partners, _("Request closed."))

    def action_reopen(self):
        for rec in self:
            if not self.env.user.has_group('engineering_change.group_ec_manager'):
                raise UserError(_("Only Line Manager can reopen a request."))
            if rec.state != 'done':
                raise UserError(_("Only Done requests can be reopened."))
            rec.with_context(ec_workflow_write=True).write(
                {'state': 'sale', 'close_date': False})
            partners = (rec.engineer_id | rec.implement_team_ids).mapped('partner_id')
            rec._notify(partners, _("Request reopened by %s.") % self.env.user.name)

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
        state_labels = self._state_labels()
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
