from odoo import fields, models


class ProjectProject(models.Model):
    _inherit = 'project.project'

    qc_checksheet_progress = fields.Char(
        string='QC Check Sheets', compute='_compute_qc_checksheet_progress',
        groups='qc_checksheet.group_qc_user',
        help="Required Check Sheet Types with a Released sheet, out of all required Types.")

    def _compute_qc_checksheet_progress(self):
        required = self.env['qc.checksheet.type'].search_count([('required', '=', True)])
        released = self.env['qc.checksheet']._read_group(
            [('job_number', 'in', self.ids), ('state', '=', 'released'), ('type_id.required', '=', True)],
            ['job_number'], ['type_id:count_distinct'])
        released_by_job = {job.id: count for job, count in released}
        for project in self:
            project.qc_checksheet_progress = f'{released_by_job.get(project.id, 0)}/{required}'

    def action_open_qc_job(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'qc_checksheet.job',
            'name': f'QC: {self.display_name}',
            'context': {'active_id': self.id},
        }
