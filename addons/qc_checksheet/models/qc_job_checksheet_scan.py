from odoo import _, api, fields, models
from odoo.exceptions import AccessError

from .qc_checksheet import GROUP_ADMIN


class QcJobChecksheetScan(models.Model):
    """The signed paper of a Job's check sheet, scanned: one or more files
    (PDF, JPG, PNG) uploaded together, with the date the Job was checked.

    It records which Revision was checked, so a later change of the Job's
    Revision can tell whether the inspection still covers it. Created by the
    Job sheet's upload (as sudo, after checking the user may author), and only
    a QC Administrator deletes one.
    """
    _name = 'qc.job.checksheet.scan'
    _description = 'Scan of a Job check sheet'
    _order = 'check_date desc, id desc'

    job_sheet_id = fields.Many2one(
        'qc.job.checksheet', string='Job Check Sheet', required=True, index=True, ondelete='cascade')
    job_id = fields.Many2one(related='job_sheet_id.job_id', store=True, string='Job Number')
    type_id = fields.Many2one(related='job_sheet_id.type_id', store=True, string='Type')
    checksheet_id = fields.Many2one(
        'qc.checksheet', string='Revision Checked', required=True, ondelete='restrict',
        help="The Revision the Job was pinned to when this was scanned: the one the inspection was done on.")
    # No sum in a group header: adding up Revision numbers means nothing.
    revision = fields.Integer(related='checksheet_id.revision', string='Rev', aggregator=False)
    check_date = fields.Date(
        string='Check Date', required=True,
        help="The day the Job was actually inspected, which may be before the day the scan is uploaded.")
    note = fields.Char()
    uploaded_by_id = fields.Many2one(
        'res.users', string='Uploaded By', readonly=True, default=lambda self: self.env.user)
    uploaded_date = fields.Datetime(string='Uploaded On', readonly=True, default=fields.Datetime.now)
    attachment_ids = fields.One2many(
        'ir.attachment', 'res_id', string='Files', bypass_search_access=True,
        domain=lambda self: [('res_model', '=', self._name)])
    file_count = fields.Integer(compute='_compute_files')
    total_size = fields.Integer(string='Size (bytes)', compute='_compute_files', aggregator=False)

    @api.depends('attachment_ids.file_size')
    def _compute_files(self):
        for rec in self:
            rec.file_count = len(rec.attachment_ids)
            rec.total_size = sum(rec.attachment_ids.mapped('file_size'))

    @api.depends('job_id.name', 'type_id.name', 'revision', 'check_date')
    def _compute_display_name(self):
        # The Jobs read as sudo once for all the records, not one by one.
        job_names = {job.id: job.name for job in self.job_id.sudo()}
        for rec in self:
            rec.display_name = f'{job_names.get(rec.job_id.id)} · {rec.type_id.name} · Rev {rec.revision} · {rec.check_date}'

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            raise AccessError(_("A scan is uploaded from the Job's QC page."))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su:
            raise AccessError(_("A scan can't be changed. Ask a QC Administrator to delete it and upload it again."))
        return super().write(vals)

    def unlink(self):
        if not self.env.su:
            if not self.env.user.has_group(GROUP_ADMIN):
                raise AccessError(_("Only a QC Administrator can delete a scan."))
            for rec in self:
                rec.job_sheet_id.sudo().message_post(body=_(
                    "Scan of Rev %(rev)s checked on %(date)s, uploaded by %(who)s (%(count)s file(s)), "
                    "deleted by %(user)s.",
                    rev=rec.revision, date=rec.check_date, who=rec.uploaded_by_id.name or '-',
                    count=rec.file_count, user=self.env.user.name))
        sheets = {rec.job_sheet_id: rec.check_date for rec in self}
        result = super().unlink()
        # The Job's Check Date was that of its latest scan: it doesn't stay on a date nothing backs up now.
        for sheet, deleted_date in sheets.items():
            sheet = sheet.sudo()
            if sheet.check_date == deleted_date:
                sheet.check_date = max(sheet.scan_ids.mapped('check_date'), default=False)
        return result
