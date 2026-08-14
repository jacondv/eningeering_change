from odoo import fields, models


class EngineeringChangeApproveWizard(models.TransientModel):
    _name = 'engineering.change.approve.wizard'
    _description = 'Engineering Change Approve Wizard'

    change_id = fields.Many2one('engineering.change', required=True)
    note = fields.Text(required=True)
    approve_by = fields.Selection([
        ('manager', 'Manager'),
        ('bod', 'BOD'),
    ], required=True)

    def action_confirm_approve(self):
        self.ensure_one()
        self.change_id._apply_approve(self.note, self.approve_by)
        return {'type': 'ir.actions.act_window_close'}
