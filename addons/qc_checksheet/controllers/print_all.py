from odoo import http
from odoo.http import content_disposition, request


class QcChecksheetPrintAll(http.Controller):

    @http.route('/qc_checksheet/print_all', type='http', auth='user', methods=['POST'])
    def print_all(self, ids='', combined='0', **kwargs):
        """The Job QC page's Print All: one PDF per sheet in a ZIP, or one combined PDF."""
        sheet_ids = [int(value) for value in ids.split(',') if value.strip().isdigit()]
        sheets = request.env['qc.checksheet'].browse(sheet_ids).exists()
        name, content, mimetype = sheets._print_files(combined=combined == '1')
        return request.make_response(content, [
            ('Content-Type', mimetype),
            ('Content-Length', len(content)),
            ('Content-Disposition', content_disposition(name)),
        ])
