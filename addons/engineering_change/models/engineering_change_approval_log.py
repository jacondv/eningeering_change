from odoo import fields, models


class EngineeringChangeApprovalLog(models.Model):
    """One immutable row per Approve/Reject decision at the Manager or BOD
    stage - unlike bod_approver_id/reject_reason on engineering.change
    (single fields, overwritten on every cycle), this keeps every decision
    across however many Reject-and-resubmit cycles a request goes through.
    Feeds both the "Comment" tab on the EC form and the "Approved by"
    table on the printed report.
    """
    _name = 'engineering.change.approval.log'
    _description = 'Engineering Change Approval/Reject Log'
    _order = 'date desc, id desc'

    change_id = fields.Many2one('engineering.change', required=True, ondelete='cascade', index=True)
    role = fields.Selection([
        ('manager', 'Manager'),
        ('bod', 'BOD'),
    ], required=True)
    decision = fields.Selection([
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], required=True)
    user_id = fields.Many2one('res.users', required=True, default=lambda self: self.env.user)
    date = fields.Datetime(required=True, default=fields.Datetime.now)
    note = fields.Text(required=True)
