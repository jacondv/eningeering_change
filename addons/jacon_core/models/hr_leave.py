import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

LEAVE_NOTIFICATION_CHANNEL_NAME_PARAM = 'jacon_core.leave_notification_channel_name'
DEFAULT_LEAVE_NOTIFICATION_CHANNEL_NAME = 'Jacon Equipment'


class HrLeave(models.Model):
    _inherit = 'hr.leave'

    @api.model_create_multi
    def create(self, vals_list):
        leaves = super().create(vals_list)
        leaves.sudo()._notify_leave_registered()
        return leaves

    def _notify_leave_registered(self):
        """Post + pin an announcement in the company-wide Discuss channel
        (name configurable via the ir.config_parameter above, default
        'Jacon Equipment') for every new time off request, right when it's
        created - even before approval, so everyone sees it early rather
        than only once (and if) it later gets approved.

        Looked up by NAME on every call rather than cached by id, so if
        the channel is ever deleted and recreated under the same name this
        keeps working without a code change - only an actual rename needs
        the parameter updated (Settings > Technical > System Parameters).
        A missing channel must never block creating the leave request
        itself - this only logs a warning and skips the announcement.
        """
        channel_name = self.env['ir.config_parameter'].sudo().get_param(
            LEAVE_NOTIFICATION_CHANNEL_NAME_PARAM, DEFAULT_LEAVE_NOTIFICATION_CHANNEL_NAME)
        channel = self.env['discuss.channel'].sudo().search([('name', '=', channel_name)], limit=1)
        if not channel:
            _logger.warning(
                "Leave notification channel %r not found - skipping the Discuss "
                "announcement for %d new time off request(s). Set the "
                "%s system parameter if the channel was renamed.",
                channel_name, len(self), LEAVE_NOTIFICATION_CHANNEL_NAME_PARAM)
            return
        for leave in self:
            date_from = fields.Date.to_date(leave.date_from) if leave.date_from else False
            date_to = fields.Date.to_date(leave.date_to) if leave.date_to else False
            if date_from and date_to and date_from == date_to:
                when = date_from.strftime('%d/%m/%Y')
            elif date_from and date_to:
                when = '%s - %s' % (date_from.strftime('%d/%m/%Y'), date_to.strftime('%d/%m/%Y'))
            else:
                when = _('Unspecified dates')
            body = _(
                '📌 %(employee)s registered time off (%(leave_type)s): %(when)s',
                employee=leave.employee_id.name,
                leave_type=leave.holiday_status_id.name or _('Time Off'),
                when=when,
            )
            message = channel.sudo().message_post(
                body=body, message_type='comment', subtype_xmlid='mail.mt_comment')
            channel.sudo().set_message_pin(message.id, True)
