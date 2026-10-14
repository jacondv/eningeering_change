from odoo import models

from .res_config_settings import DEFAULT_TAB_TITLE, PARAM_PREFIX


class ResCompany(models.Model):
    _inherit = 'res.company'

    # Read from server-rendered templates (login page, emails, portal) via
    # `res_company`, which QWeb provides on every render.

    def jacon_debranding_hidden(self, key):
        """Whether the debranding switch `key` (e.g. 'hide_login_powered_by') is on."""
        return self.env['ir.config_parameter'].sudo().get_param(PARAM_PREFIX + key) == 'True'

    def jacon_debranding_tab_title(self):
        """The text to show instead of "Odoo" in the browser tab, or False to keep "Odoo"."""
        params = self.env['ir.config_parameter'].sudo()
        if params.get_param(PARAM_PREFIX + 'replace_tab_title') != 'True':
            return False
        return params.get_param(PARAM_PREFIX + 'tab_title') or DEFAULT_TAB_TITLE
