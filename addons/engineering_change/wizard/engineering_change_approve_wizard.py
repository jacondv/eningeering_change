from odoo import fields, models


class EngineeringChangeApproveWizard(models.TransientModel):
    _name = 'engineering.change.approve.wizard'
    _description = 'Engineering Change Approve Wizard'

    change_id = fields.Many2one('engineering.change', required=True)
    note = fields.Text()
    approve_by = fields.Selection([
        ('manager', 'Line Manager'),
        ('head_office', 'Head Manager'),
        ('bod', 'BOC'),
    ], required=True)

    def action_confirm_approve(self):
        self.ensure_one()
        self.change_id._apply_approve(self.note, self.approve_by)
        return {'type': 'ir.actions.act_window_close'}
