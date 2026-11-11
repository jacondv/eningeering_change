from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from .qc_checksheet import ACTIVITY_TODO, GROUP_APPROVER


class QcJobChecksheetChange(models.Model):
    """A request to move a Job, already pinned to a Revision, to another one.
    It changes nothing until an Approver approves it; then the Job's pin moves
    (see qc.job.checksheet._apply_revision) and the request is closed.

    Only the workflow methods change it, as sudo after checking the user's
    group, like qc.checksheet's.
    """
    _name = 'qc.job.checksheet.change'
    _description = 'Job Check Sheet Revision Change Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _mail_post_access = 'read'

    job_sheet_id = fields.Many2one(
        'qc.job.checksheet', string='Job Check Sheet', required=True, index=True, ondelete='cascade')
    job_id = fields.Many2one(related='job_sheet_id.job_id', store=True, string='Job Number')
    type_id = fields.Many2one(related='job_sheet_id.type_id', store=True, string='Type')
    from_checksheet_id = fields.Many2one(
        'qc.checksheet', string='From', required=True, ondelete='restrict',
        help="The Revision the Job prints when it was requested.")
    to_checksheet_id = fields.Many2one(
        'qc.checksheet', string='To', required=True, ondelete='restrict', tracking=True,
        help="The Revision the Job prints once approved.")
    from_revision = fields.Integer(related='from_checksheet_id.revision', string='From Rev')
    to_revision = fields.Integer(related='to_checksheet_id.revision', string='To Rev')
    reason = fields.Char(string='Reason', required=True)
    state = fields.Selection([
        ('pending', 'Pending Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
    ], default='pending', required=True, readonly=True, copy=False, tracking=True, index=True)
    requested_by_id = fields.Many2one(
        'res.users', string='Requested By', readonly=True, default=lambda self: self.env.user)
    requested_date = fields.Datetime(string='Requested On', readonly=True, default=fields.Datetime.now)
    decided_by_id = fields.Many2one('res.users', string='Decided By', readonly=True)
    decided_date = fields.Datetime(string='Decided On', readonly=True)
    reject_reason = fields.Char(string='Reject Reason', readonly=True)
    has_scan = fields.Boolean(
        compute='_compute_has_scan', help="The Job already has a signed scan: approving asks whether it needs a new inspection.")
    reinspection = fields.Selection([
        ('required', 'Re-inspection required'),
        ('skipped', 'Re-inspection skipped'),
    ], string='Re-inspection', readonly=True,
        help="What the Approver decided, when the Job already had a scan at the time.")
    reinspection_reason = fields.Char(string='Why No Re-inspection', readonly=True)

    @api.depends('job_sheet_id.scan_ids')
    def _compute_has_scan(self):
        scanned = {
            sheet.id for [sheet] in self.env['qc.job.checksheet.scan'].sudo()._read_group(
                [('job_sheet_id', 'in', self.job_sheet_id.ids)], ['job_sheet_id'])
        }
        for rec in self:
            rec.has_scan = rec.job_sheet_id.id in scanned

    @api.depends('job_id', 'type_id', 'from_revision', 'to_revision')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f'{rec.job_id.sudo().name} · {rec.type_id.name}: Rev {rec.from_revision} → Rev {rec.to_revision}'

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            raise UserError(_("Request a change from the Job's QC page."))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su:
            raise UserError(_("A request is changed by approving, rejecting or cancelling it."))
        return super().write(vals)

    def unlink(self):
        if not self.env.su and self.filtered(lambda rec: rec.state == 'pending'):
            raise UserError(_("Cancel a pending request instead of deleting it."))
        return super().unlink()

    # Workflow

    def _check_approver(self):
        if not self.env.su and not self.env.user.has_group(GROUP_APPROVER):
            raise AccessError(_("You don't have the access rights for this action."))

    def _check_pending(self):
        for rec in self:
            if rec.state != 'pending':
                raise UserError(_("%s is no longer pending.", rec.display_name))

    def _clear_activities(self):
        self.sudo().activity_unlink([ACTIVITY_TODO])

    def _notify_approvers(self, waiting_days=0):
        """Every Approver gets a To-Do on the request. Odoo itself tells the assignee
        in their Discuss Inbox (or by email, as their notification setting says), with
        a link to the request, so it doesn't go unseen until someone opens the Job's
        QC page. A reminder is a new To-Do, titled so it can't be mistaken for the first."""
        approvers = self.env.ref(GROUP_APPROVER).sudo().user_ids
        for rec in self:
            if waiting_days:
                summary = _("Still waiting for %(days)s days: approve %(name)s", days=waiting_days, name=rec.display_name)
            else:
                summary = _("Approve %s", rec.display_name)
            for approver in approvers:
                rec.sudo().activity_schedule(
                    ACTIVITY_TODO, user_id=approver.id, summary=summary,
                    note=_("%(user)s: %(reason)s", user=rec.requested_by_id.name, reason=rec.reason))

    @api.model
    def _cron_remind_approvers(self):
        """Daily: a request waiting longer than the Dashboard's "waiting too long"
        setting reminds the Approvers again, with a fresh To-Do."""
        days = self.env['qc.checksheet']._overdue_days()
        before = fields.Datetime.now() - timedelta(days=days)
        for rec in self.search([('state', '=', 'pending'), ('requested_date', '<=', before)]):
            rec._clear_activities()
            rec._notify_approvers(waiting_days=(fields.Datetime.now() - rec.requested_date).days)

    def action_approve(self, reinspection=None, reinspection_reason=None):
        """A Job that already has a scan needs the Approver's word on re-inspection:
        'required' (the Job must be inspected again, and shows as such until it is)
        or 'skipped', with why (the earlier scan stays as the inspection)."""
        self._check_approver()
        self._check_pending()
        reason = (reinspection_reason or '').strip()
        for rec in self:
            if rec.has_scan:
                if reinspection not in ('required', 'skipped'):
                    raise UserError(_(
                        "%s already has a scan. Choose whether it needs a new inspection.", rec.job_id.sudo().name))
                if reinspection == 'skipped' and not reason:
                    raise UserError(_("Enter why no new inspection is needed."))
        for rec in self:
            decision = rec.has_scan and reinspection or False
            rec.job_sheet_id.sudo()._apply_revision(
                rec.to_checksheet_id, rec.reason, requested_by=rec.requested_by_id, approved_by=self.env.user,
                reinspection=decision)
            sudo_rec = rec.sudo()
            sudo_rec.write({
                'state': 'approved', 'decided_by_id': self.env.uid, 'decided_date': fields.Datetime.now(),
                'reinspection': decision, 'reinspection_reason': reason if decision == 'skipped' else False})
            rec._clear_activities()
            sudo_rec.message_post(body=_("Approved by %s.", self.env.user.name))
        return True

    def action_open_approve(self):
        """The form's Approve button: a Job with a scan asks about re-inspection first."""
        self.ensure_one()
        self._check_approver()
        self._check_pending()
        if not self.has_scan:
            return self.action_approve()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Approve Revision change"),
            'res_model': 'qc.job.change.approve.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_change_id': self.id},
        }

    def action_reject(self, reason):
        self._check_approver()
        self._check_pending()
        if not (reason or '').strip():
            raise UserError(_("Enter the reason for rejecting."))
        for rec in self:
            sudo_rec = rec.sudo()
            sudo_rec.write({
                'state': 'rejected', 'reject_reason': reason.strip(),
                'decided_by_id': self.env.uid, 'decided_date': fields.Datetime.now()})
            rec._clear_activities()
            sudo_rec.message_post(body=_("Rejected by %(user)s: %(reason)s", user=self.env.user.name, reason=reason.strip()))
            sudo_rec.job_sheet_id._log(_(
                "Change to %(new)s rejected by %(user)s: %(reason)s",
                new=rec.to_checksheet_id.display_name, user=self.env.user.name, reason=reason.strip()))
            if rec.requested_by_id:
                sudo_rec.activity_schedule(
                    ACTIVITY_TODO, user_id=rec.requested_by_id.id,
                    summary=_("Rejected: %s", rec.display_name), note=reason.strip())
        return True

    def action_cancel(self):
        """By whoever asked for it, or by an Approver."""
        self._check_pending()
        for rec in self:
            if not self.env.su and rec.requested_by_id != self.env.user \
                    and not self.env.user.has_group(GROUP_APPROVER):
                raise AccessError(_("Only the person who asked, or an Approver, can cancel this request."))
            sudo_rec = rec.sudo()
            sudo_rec.write({'state': 'cancelled'})
            rec._clear_activities()
            sudo_rec.message_post(body=_("Cancelled by %s.", self.env.user.name))
            sudo_rec.job_sheet_id._log(_(
                "Change to %(new)s cancelled by %(user)s.",
                new=rec.to_checksheet_id.display_name, user=self.env.user.name))
        return True

    def action_open_job_sheet(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'qc_checksheet.job',
            'name': f'QC: {self.job_id.sudo().display_name}',
            'context': {'active_id': self.job_id.id},
        }
