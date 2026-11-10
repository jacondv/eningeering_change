import base64
from urllib.parse import quote

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from .qc_checksheet import GROUP_ADMIN, GROUP_AUTHOR
from .qc_scan_files import KINDS, LEVELS, MAX_FILES, check_file, compress, human_size, max_file_size


class QcJobChecksheet(models.Model):
    """What came of a Job's check sheet once it was printed, checked and signed: the
    scans uploaded, and whether they cover the Revision the Job is pinned to now."""
    _inherit = 'qc.job.checksheet'

    scan_ids = fields.One2many('qc.job.checksheet.scan', 'job_sheet_id', string='Scans')
    scan_count = fields.Integer(compute='_compute_scan_count')
    inspection_state = fields.Selection([
        ('awaiting', 'Awaiting scan'),
        ('scanned', 'Scanned'),
        ('reinspection', 'Re-inspection needed'),
    ], string='Inspection', compute='_compute_inspection_state', store=True, index=True,
        help="Awaiting scan: no signed scan yet. Scanned: a scan was made on the Revision the Job prints now, "
             "or its re-inspection was skipped. Re-inspection needed: the Job's Revision changed since the scan.")
    reinspection_waived_id = fields.Many2one(
        'qc.checksheet', string='Re-inspection Skipped For', readonly=True, ondelete='set null',
        help="Set when an Approver approved moving the Job to this Revision without a new inspection.")

    @api.depends('scan_ids')
    def _compute_scan_count(self):
        for rec in self:
            rec.scan_count = len(rec.scan_ids)

    @api.depends('scan_ids.checksheet_id', 'checksheet_id', 'reinspection_waived_id')
    def _compute_inspection_state(self):
        for rec in self:
            if not rec.scan_ids:
                rec.inspection_state = 'awaiting'
            elif rec.checksheet_id in rec.scan_ids.checksheet_id or rec.reinspection_waived_id == rec.checksheet_id:
                rec.inspection_state = 'scanned'
            else:
                rec.inspection_state = 'reinspection'

    # Uploading

    def _check_author(self):
        if not self.env.su and not self.env.user.has_group(GROUP_AUTHOR):
            raise AccessError(_("You don't have the access rights for this action."))

    @api.model
    def _prepare_scan_files(self, files, level=None):
        """[(name, bytes)] -> [{name, data, mimetype, original_size, size, reduced}], each checked, and
        made smaller at `level` ('standard', 'strong') when there is one."""
        if not files:
            raise UserError(_("Choose at least one file."))
        if len(files) > MAX_FILES:
            raise UserError(_("At most %s files at a time.", MAX_FILES))
        if level and level not in LEVELS:
            raise UserError(_("Unknown way of reducing the size: %s.", level))
        max_size = max_file_size(self.env)
        prepared = []
        for name, data in files:
            if level:
                prepared.append(compress(name, data, level, max_size))
            else:
                kind = check_file(name, data, max_size)
                prepared.append({
                    'name': name, 'data': data, 'mimetype': KINDS[kind][0],
                    'original_size': len(data), 'size': len(data), 'reduced': False})
        return prepared

    @api.model
    def scan_estimate(self, files):
        """What each way of reducing would leave of each file, to choose from before uploading:
        [(name, bytes)] -> [{name, size, standard: {...}, strong: {...}}], each level with
        {estimated_size, estimated_name, reduced}."""
        self._check_author()
        by_level = {level: self._prepare_scan_files(files, level) for level in LEVELS}
        return [{
            'name': name,
            'size': by_level['standard'][index]['original_size'],
            **{level: {
                'estimated_size': by_level[level][index]['size'],
                'estimated_name': by_level[level][index]['name'],
                'reduced': by_level[level][index]['reduced'],
            } for level in LEVELS},
        } for index, (name, _data) in enumerate(files)]

    @api.model
    def scan_limits(self):
        """What the upload dialog checks files against: the Setting's size, and how many files at a time."""
        return {'max_file_size': max_file_size(self.env), 'max_files': MAX_FILES}

    def scan_upload(self, files, check_date, note=None, level=None):
        """Store a scan of this Job sheet: [(name, bytes)] checked on `check_date`, made smaller at
        `level` ('standard', 'strong') if given. The Job's Check Date becomes that of its latest
        scan. Returns the scan's id."""
        self.ensure_one()
        self._check_author()
        check_date = fields.Date.to_date(check_date)
        if not check_date:
            raise UserError(_("Enter the Check Date: the day the Job was inspected."))
        if check_date > fields.Date.context_today(self):
            raise UserError(_("The Check Date can't be in the future."))
        prepared = self._prepare_scan_files(files, level)
        scan = self.env['qc.job.checksheet.scan'].sudo().create({
            'job_sheet_id': self.id,
            'checksheet_id': self.checksheet_id.id,
            'check_date': check_date,
            'note': (note or '').strip() or False,
            'uploaded_by_id': self.env.uid,
        })
        for item in prepared:
            self.env['ir.attachment'].sudo().create({
                'name': item['name'],
                'datas': base64.b64encode(item['data']),
                'mimetype': item['mimetype'],
                'res_model': scan._name,
                'res_id': scan.id,
            })
        sudo_self = self.sudo()
        sudo_self.check_date = max(sudo_self.scan_ids.mapped('check_date'))
        before = sum(item['original_size'] for item in prepared)
        after = sum(item['size'] for item in prepared)
        sudo_self.message_post(body=_(
            "Scan of Rev %(rev)s uploaded by %(user)s: checked on %(date)s, %(count)s file(s), %(size)s%(reduced)s.",
            rev=self.revision, user=self.env.user.name, date=check_date, count=len(prepared), size=human_size(after),
            reduced=_(" (reduced from %s)", human_size(before)) if after < before else ''))
        return scan.id

    # Reaching the Job's QC page from a list: the row, and the button that goes straight to the upload

    def _job_page_action(self, upload=False):
        """The Job's QC page, scrolled to this sheet's row and highlighted; with `upload` its Upload scan
        dialog opens by itself."""
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'qc_checksheet.job',
            'name': f'QC: {self.job_id.sudo().display_name}',
            'context': {'active_id': self.job_id.id, 'focus_type_id': self.type_id.id, 'focus_upload': upload},
        }

    def action_open_job_page(self):
        return self._job_page_action()

    def action_upload_scan(self):
        self._check_author()
        return self._job_page_action(upload=True)

    # Job QC page

    @api.model
    def _scan_summary(self, scan, pinned):
        return {
            'id': scan.id,
            'revision': scan.revision,
            'check_date': fields.Date.to_string(scan.check_date),
            'uploaded_by': scan.uploaded_by_id.name or '',
            'uploaded_date': fields.Datetime.to_string(scan.uploaded_date) or '',
            'note': scan.note or '',
            'covers_current': scan.checksheet_id == pinned,
            'total_size': human_size(scan.total_size),
            'files': [{
                'id': attachment.id,
                'name': attachment.name,
                'size': human_size(attachment.file_size),
                'url': f'/web/content/{attachment.id}?filename={quote(attachment.name)}',
            } for attachment in scan.attachment_ids.sorted('id')],
        }

    @api.model
    def job_overview(self, job_id):
        data = super().job_overview(job_id)
        user = self.env.user
        can_upload = user.has_group(GROUP_AUTHOR)
        can_delete = user.has_group(GROUP_ADMIN)
        job_sheets = self.browse([row['pinned']['job_sheet_id'] for row in data['rows'] if row['pinned']])
        by_id = {rec.id: rec for rec in job_sheets}
        states = dict(self._fields['inspection_state'].selection)
        # Read together, not one Job sheet after the other.
        job_sheets.scan_ids.attachment_ids.mapped('file_size')
        job_sheets.scan_ids.mapped('uploaded_by_id.name')
        for row in data['rows']:
            rec = by_id.get(row['pinned']['job_sheet_id']) if row['pinned'] else None
            row['inspection'] = {
                'state': rec.inspection_state,
                'state_label': states[rec.inspection_state],
                'waived': bool(rec.reinspection_waived_id == rec.checksheet_id and rec.scan_ids),
                'can_upload': can_upload,
                'can_delete': can_delete,
                'scans': [self._scan_summary(scan, rec.checksheet_id) for scan in rec.scan_ids],
            } if rec else False
            if row['pending'] and rec:
                row['pending']['has_scan'] = bool(rec.scan_ids)
        data['scan_limits'] = self.scan_limits()
        data['scanned'] = sum(1 for row in data['rows'] if row['required'] and row['inspection'] and row['inspection']['state'] == 'scanned')
        return data
