from odoo import _, fields, models
from odoo.exceptions import AccessError, UserError


class EngineeringChange(models.Model):
    """The request's state machine (Submit / Approve / Reject / Confirm
    Production / Close / Reopen / Revert) and the notification helpers it
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

    # ------------------------------------------------------------
    # Reject wizard glue
    # ------------------------------------------------------------
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
