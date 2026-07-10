from odoo import fields, models


class EngineeringChangeRejectWizard(models.TransientModel):
    _name = 'engineering.change.reject.wizard'
    _description = 'Engineering Change Reject Wizard'

    change_id = fields.Many2one('engineering.change', required=True)
    reject_reason = fields.Text(required=True)
    reject_by = fields.Selection([
        ('manager', 'Manager'),
        ('bod', 'BOD'),
    ], required=True)

    def action_confirm_reject(self):
        self.ensure_one()
        self.change_id._apply_reject(self.reject_reason, self.reject_by)
        return {'type': 'ir.actions.act_window_close'}
