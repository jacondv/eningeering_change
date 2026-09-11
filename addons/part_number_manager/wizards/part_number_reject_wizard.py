from odoo import _, models
from odoo.exceptions import UserError


class PartNumberRejectWizard(models.TransientModel):
    """Plain Confirm/Cancel before Head Engineer rejects (= Archives, not
    deletes) however many Part Numbers were selected on the "Pending
    Approval" list - no reason field, see
    part_number_manager.part_number.action_reject().
    """
    _name = 'part_number_manager.part_number_reject_wizard'
    _description = 'Reject Part Number(s)'

    def action_confirm(self):
        part_ids = self.env.context.get('active_ids') or []
        if not part_ids:
            raise UserError(_('No Part Number was selected.'))
        self.env['part_number_manager.part_number'].browse(part_ids).action_reject()
        return {'type': 'ir.actions.act_window_close'}
