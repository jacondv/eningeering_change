import re

from odoo import api, fields, models

# Not allowed in a file name on Windows, and / anywhere.
UNSAFE_FILE_CHARS = re.compile(r'[\\/:*?"<>|]+')


def safe_file_name(name):
    """A file name without characters a file system refuses, in capitals (the extension is added by the caller)."""
    return re.sub(r'\s+', ' ', UNSAFE_FILE_CHARS.sub('', name)).strip().upper()


class QcChecksheet(models.Model):
    """File name of a Model's sheet printed blank, without any Job. A Job's
    own print is qc.job.checksheet's."""
    _inherit = 'qc.checksheet'

    pdf_file_name = fields.Char(
        compute='_compute_pdf_file_name',
        help="<NUMBER>-REV<N> in capitals, e.g. QC-GE-ZA90-REV1.")

    @api.depends('reference', 'name', 'revision')
    def _compute_pdf_file_name(self):
        for rec in self:
            rec.pdf_file_name = safe_file_name(f'{rec.reference or rec.name or ""}-REV{rec.revision}')
