from odoo import _, models
from odoo.exceptions import UserError


class PartNumberApproveWizard(models.TransientModel):
    """Plain Confirm/Cancel before Head Engineer approves however many Part
    Numbers were selected on the "Pending Approval" list - see
    part_number_manager.part_number.action_approve().
    """
    _name = 'part_number_manager.part_number_approve_wizard'
    _description = 'Approve Part Number(s)'

    def action_confirm(self):
        part_ids = self.env.context.get('active_ids') or []
        if not part_ids:
            raise UserError(_('No Part Number was selected.'))
        self.env['part_number_manager.part_number'].browse(part_ids).action_approve()
        return {'type': 'ir.actions.act_window_close'}
