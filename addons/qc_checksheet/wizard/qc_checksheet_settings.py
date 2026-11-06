from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..models.qc_checksheet import GROUP_ADMIN
from ..models.qc_checksheet_dashboard import OVERDUE_DAYS_PARAM


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

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        res['review_overdue_days'] = self.env['qc.checksheet']._overdue_days()
        return res

    def action_save(self):
        self.ensure_one()
        if not self.env.user.has_group(GROUP_ADMIN):
            raise UserError(_("Only a QC Check Sheet Administrator can change these settings."))
        if self.review_overdue_days < 1:
            raise UserError(_("The number of days must be at least 1."))
        self.env['ir.config_parameter'].sudo().set_param(OVERDUE_DAYS_PARAM, self.review_overdue_days)
        return {'type': 'ir.actions.act_window_close'}
