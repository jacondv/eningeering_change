from odoo import http
from odoo.exceptions import AccessError, UserError
from odoo.http import request

from ..models.qc_scan_files import MAX_FILES, human_size, max_file_size


def _files():
    """The files of the request as [(name, bytes)]; the page sends them as `ufile`. Their number and size
    are checked before they are held in memory, so a huge request is refused, not read."""
    uploads = request.httprequest.files.getlist('ufile')
    if len(uploads) > MAX_FILES:
        raise UserError(request.env._("At most %s files at a time.", MAX_FILES))
    limit = max_file_size(request.env)
    files = []
    for upload in uploads:
        name = upload.filename or 'scan'
        data = upload.read(limit + 1)
        if len(data) > limit:
            raise UserError(request.env._(
                "%(name)s is over the %(limit)s a file may be. Reduce its size first.",
                name=name, limit=human_size(limit)))
        files.append((name, data))
    return files


def _error(error):
    return request.make_json_response({'error': str(error.args[0] if error.args else error)}, status=400)


class QcChecksheetScan(http.Controller):

    @http.route('/qc_checksheet/scan/estimate', type='http', auth='user', methods=['POST'])
    def estimate(self, **kwargs):
        """What each file would weigh once reduced, without storing anything."""
        try:
            files = request.env['qc.job.checksheet'].scan_estimate(_files())
        except (UserError, AccessError) as error:
            return _error(error)
        return request.make_json_response({'files': files})

    @http.route('/qc_checksheet/scan/upload', type='http', auth='user', methods=['POST'])
    def upload(self, job_sheet_id, check_date, note='', reduce='none', **kwargs):
        """Store the signed scan of a Job's check sheet. The files arrive as a multipart
        request, so a 25 MB scan isn't wrapped in JSON on its way."""
        try:
            job_sheet = request.env['qc.job.checksheet'].browse(int(job_sheet_id)).exists()
            if not job_sheet:
                raise UserError(request.env._("This check sheet no longer exists."))
            # 'none' (or nothing) stores the files as they are; '1' is how an older page said "reduce".
            level = {'1': 'standard'}.get(reduce, reduce if reduce not in ('', '0', 'none') else None)
            scan_id = job_sheet.scan_upload(_files(), check_date, note, level=level)
        except (UserError, AccessError) as error:
            return _error(error)
        return request.make_json_response({'scan_id': scan_id})
