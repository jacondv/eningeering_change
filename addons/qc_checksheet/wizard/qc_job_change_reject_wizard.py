from odoo import fields, models


class QcJobChangeRejectWizard(models.TransientModel):
    """"Reject" button on a Revision change request: the Approver says why the Job stays on its Revision."""
    _name = 'qc.job.change.reject.wizard'
    _description = 'Reject a Job Revision Change'

    change_id = fields.Many2one('qc.job.checksheet.change', required=True)
    reason = fields.Char(string='Reject Reason', required=True)

    def action_reject(self):
        self.ensure_one()
        self.change_id.action_reject(self.reason)
        return {'type': 'ir.actions.act_window_close'}
