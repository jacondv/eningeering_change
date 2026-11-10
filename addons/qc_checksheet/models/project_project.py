from odoo import fields, models


class ProjectProject(models.Model):
    _inherit = 'project.project'

    qc_job_checksheet_ids = fields.One2many('qc.job.checksheet', 'job_id', string='Printed QC Check Sheets')
    qc_checksheet_progress = fields.Char(
        string='QC Check Sheets', compute='_compute_qc_checksheet_progress',
        groups='qc_checksheet.group_qc_user',
        help="Required Check Sheet Types the Job can print - already printed, or Released on its Model - "
             "out of all required Types.")

    def _qc_ready_types(self, required_types):
        """{Job id: ids of the required Types it can print}: already printed,
        or Released on its Model."""
        pinned = self.env['qc.job.checksheet'].sudo()._read_group(
            [('job_id', 'in', self.ids), ('type_id', 'in', required_types.ids)], ['job_id'], ['type_id:array_agg'])
        pinned_by_job = {job.id: set(type_ids) for job, type_ids in pinned}
        # Released on its Model, or on the Model whose sheet it uses.
        released_by_model = self.env['qc.checksheet.share']._ready_types(self.sudo().model_id, required_types)
        return {
            job.id: pinned_by_job.get(job.id, set()) | released_by_model.get(job.sudo().model_id.id, set())
            for job in self
        }

    def _compute_qc_checksheet_progress(self):
        # Active required Types only, on both sides, like the Job QC page.
        required_types = self.env['qc.checksheet.type']._required_types()
        ready = self._qc_ready_types(required_types)
        for project in self:
            project.qc_checksheet_progress = f'{len(ready[project.id])}/{len(required_types)}'

    def _qc_waiting_for_sheets(self):
        """These Jobs that still can't print every required sheet."""
        required_types = self.env['qc.checksheet.type']._required_types()
        ready = self._qc_ready_types(required_types)
        return self.filtered(lambda job: len(ready[job.id]) < len(required_types))

    def action_open_qc_job(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'qc_checksheet.job',
            'name': f'QC: {self.display_name}',
            'context': {'active_id': self.id},
        }
