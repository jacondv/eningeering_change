from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..models.qc_checksheet import GROUP_ADMIN
from ..models.qc_checksheet_dashboard import OVERDUE_DAYS_PARAM
from ..models.qc_scan_files import SCAN_MAX_FILE_MB_PARAM, max_file_size

# More than this is a different way of storing scans, not a Setting.
MAX_SCAN_FILE_MB = 200


class QcChecksheetSettings(models.TransientModel):
    """QC Check Sheet > Configuration > Settings: this module's own settings, so
    nobody has to dig through System Parameters for them. Kept apart from the
    general Settings page on purpose, and open to a QC Administrator rather
    than only to Odoo administrators."""
    _name = 'qc.checksheet.settings'
    _description = 'QC Check Sheet Settings'

    review_overdue_days = fields.Integer(
        string='Waiting for approval too long after (days)',
        help="On the Dashboard, a check sheet In Review for this many days or more is flagged.")
    scan_max_file_mb = fields.Integer(
        string='Largest scan file (MB)',
        help="The biggest PDF, JPG or PNG that can be uploaded as a scan. A web server in front of Odoo "
             "(nginx...) has its own limit, which has to be at least this much.")

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        res['review_overdue_days'] = self.env['qc.checksheet']._overdue_days()
        res['scan_max_file_mb'] = max_file_size(self.env) // (1024 * 1024)
        return res

    def action_save(self):
        self.ensure_one()
        if not self.env.user.has_group(GROUP_ADMIN):
            raise UserError(_("Only a QC Check Sheet Administrator can change these settings."))
        if self.review_overdue_days < 1:
            raise UserError(_("The number of days must be at least 1."))
        if not 1 <= self.scan_max_file_mb <= MAX_SCAN_FILE_MB:
            raise UserError(_("The largest scan file must be between 1 and %s MB.", MAX_SCAN_FILE_MB))
        self.env['ir.config_parameter'].sudo().set_param(OVERDUE_DAYS_PARAM, self.review_overdue_days)
        self.env['ir.config_parameter'].sudo().set_param(SCAN_MAX_FILE_MB_PARAM, self.scan_max_file_mb)
        return {'type': 'ir.actions.act_window_close'}
