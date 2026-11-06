import io
import re
import zipfile

from odoo import _, api, fields, models
from odoo.exceptions import UserError

REPORT_NAME = 'qc_checksheet.report_qc_checksheet_document'
# Not allowed in a file name on Windows, and / anywhere.
UNSAFE_FILE_CHARS = re.compile(r'[\\/:*?"<>|]+')


def _safe_file_name(name):
    """A file name without characters a file system refuses, in capitals (the extension is added by the caller)."""
    return re.sub(r'\s+', ' ', UNSAFE_FILE_CHARS.sub('', name)).strip().upper()


class QcChecksheet(models.Model):
    """PDF file names, and Print All of a Job's sheets: one PDF each in a ZIP,
    or one combined PDF."""
    _inherit = 'qc.checksheet'

    pdf_file_name = fields.Char(
        compute='_compute_pdf_file_name',
        help="<MACHINE SERIAL>-QC-<TYPE NAME> in capitals, or the Job Number when the machine has no Serial yet.")

    @api.depends('machine_serial', 'job_number.name', 'type_id.name')
    def _compute_pdf_file_name(self):
        for rec in self:
            rec.pdf_file_name = _safe_file_name(f'{rec._pdf_file_prefix()}-QC-{rec.type_id.name or rec.name or ""}')

    def _pdf_file_prefix(self):
        self.ensure_one()
        # The Job may be one the user can't read; its number is all that's needed.
        return self.machine_serial or self.job_number.sudo().name or self.reference or ''

    def _print_files(self, combined=False):
        """(file name, content, mimetype) of these sheets, rendered with the user's own rights."""
        if not self:
            raise UserError(_("Select at least one check sheet to print."))
        self.check_access('read')
        Report = self.env['ir.actions.report']
        prefix = _safe_file_name(self[0]._pdf_file_prefix())
        if len(self) == 1:
            pdf, _type = Report._render_qweb_pdf(REPORT_NAME, self.ids)
            return f'{self.pdf_file_name}.pdf', pdf, 'application/pdf'
        if combined:
            pdf, _type = Report._render_qweb_pdf(REPORT_NAME, self.ids)
            return f'{prefix}-QC-ALL.pdf', pdf, 'application/pdf'
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
            for sheet in self:
                pdf, _type = Report._render_qweb_pdf(REPORT_NAME, sheet.ids)
                archive.writestr(f'{sheet.pdf_file_name}.pdf', pdf)
        return f'{prefix}-QC.zip', buffer.getvalue(), 'application/zip'
