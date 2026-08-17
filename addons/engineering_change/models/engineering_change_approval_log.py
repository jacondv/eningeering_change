from odoo import fields, models


class EngineeringChangeApprovalLog(models.Model):
    """One immutable row per Approve/Reject decision at the Line Manager, Head
    Manager, or BOC stage - unlike bod_approver_id/reject_reason on engineering.change
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
        ('manager', 'Line Manager'),
        ('head_office', 'Head Manager'),
        ('bod', 'BOC'),
    ], required=True)
    decision = fields.Selection([
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], required=True)
    user_id = fields.Many2one('res.users', required=True, default=lambda self: self.env.user)
    date = fields.Datetime(required=True, default=fields.Datetime.now)
    # Required for Reject (a reason is always mandatory); left blank on Approve,
    # where a comment is optional.
    note = fields.Text()
