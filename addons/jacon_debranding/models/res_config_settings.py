from odoo import fields, models

PARAM_PREFIX = 'jacon_debranding.'
PUBLISHER_CRON_XMLID = 'mail.ir_cron_module_update_notification'
DEFAULT_TAB_TITLE = 'Jacon'


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    jacon_hide_odoo_account = fields.Boolean(
        string='Hide "My Odoo.com Account"', config_parameter=PARAM_PREFIX + 'hide_odoo_account')
    jacon_hide_help = fields.Boolean(
        string='Hide "Help"', config_parameter=PARAM_PREFIX + 'hide_help')
    jacon_hide_login_powered_by = fields.Boolean(
        string='Hide "Powered by Odoo" on the login page',
        config_parameter=PARAM_PREFIX + 'hide_login_powered_by')
    jacon_hide_manage_databases = fields.Boolean(
        string='Hide "Manage Databases" on the login page',
        config_parameter=PARAM_PREFIX + 'hide_manage_databases')
    jacon_hide_email_powered_by = fields.Boolean(
        string='Hide "Powered by Odoo" in emails', config_parameter=PARAM_PREFIX + 'hide_email_powered_by')
    jacon_hide_portal_powered_by = fields.Boolean(
        string='Hide "Powered by Odoo" in the customer portal',
        config_parameter=PARAM_PREFIX + 'hide_portal_powered_by')
    jacon_replace_tab_title = fields.Boolean(
        string='Replace "Odoo" in the browser tab', config_parameter=PARAM_PREFIX + 'replace_tab_title')
    jacon_tab_title = fields.Char(
        string='Browser tab title', config_parameter=PARAM_PREFIX + 'tab_title', default=DEFAULT_TAB_TITLE)
    jacon_disable_publisher = fields.Boolean(
        string='Stop sending database statistics to odoo.com',
        config_parameter=PARAM_PREFIX + 'disable_publisher',
        help='Switches off the weekly "Publisher: Update Notification" scheduled action.')

    def set_values(self):
        super().set_values()
        cron = self.env.ref(PUBLISHER_CRON_XMLID, raise_if_not_found=False)
        if cron and cron.active == self.jacon_disable_publisher:
            cron.sudo().active = not self.jacon_disable_publisher
