from odoo import fields, models


class QcChecksheetRejectWizard(models.TransientModel):
    """"Reject" button on the check sheet form: the Approver says why the
    sheet goes back to Draft."""
    _name = 'qc.checksheet.reject.wizard'
    _description = 'Reject QC Check Sheet'

    checksheet_id = fields.Many2one('qc.checksheet', required=True)
    reason = fields.Char(string='Reject Reason', required=True)

    def action_reject(self):
        self.ensure_one()
        self.checksheet_id.action_reject(self.reason)
        return {'type': 'ir.actions.act_window_close'}
