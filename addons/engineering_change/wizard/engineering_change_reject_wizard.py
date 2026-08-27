from odoo import fields, models


class EngineeringChangeRejectWizard(models.TransientModel):
    _name = 'engineering.change.reject.wizard'
    _description = 'Engineering Change Reject Wizard'

    change_id = fields.Many2one('engineering.change', required=True)
    reject_reason = fields.Text(required=True)
    reject_by = fields.Selection([
        ('manager', 'Line Manager'),
        ('head_office', 'Head Manager'),
        ('bod', 'BOC'),
    ], required=True)
    outcome = fields.Selection([
        ('draft', 'Back to Draft (edit and resubmit)'),
        ('cancel', 'Cancel Request (no way back)'),
    ], required=True, default='draft')

    def action_confirm_reject(self):
        self.ensure_one()
        self.change_id._apply_reject(self.reject_reason, self.reject_by, outcome=self.outcome)
        return {'type': 'ir.actions.act_window_close'}
