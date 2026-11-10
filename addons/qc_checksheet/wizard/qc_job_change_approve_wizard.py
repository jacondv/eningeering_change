from odoo import fields, models


class QcJobChangeApproveWizard(models.TransientModel):
    """"Approve" on a Revision change request of a Job that already has a scan: the
    Approver says whether the Job must be inspected again on the new Revision."""
    _name = 'qc.job.change.approve.wizard'
    _description = 'Approve a Job Revision Change'

    change_id = fields.Many2one('qc.job.checksheet.change', required=True)
    decision = fields.Selection([
        ('required', 'Re-inspection required'),
        ('skipped', 'Skip re-inspection'),
    ], string='Re-inspection', required=True, default='required')
    reason = fields.Char(string='Why No Re-inspection')
    scan_summary = fields.Char(compute='_compute_scan_summary')

    def _compute_scan_summary(self):
        for rec in self:
            scan = rec.change_id.job_sheet_id.sudo().scan_ids[:1]
            rec.scan_summary = (
                f'Inspected on Rev {scan.revision}, checked on {scan.check_date}.' if scan else '')

    def action_approve(self):
        self.ensure_one()
        self.change_id.action_approve(self.decision, self.reason)
        return {'type': 'ir.actions.act_window_close'}
