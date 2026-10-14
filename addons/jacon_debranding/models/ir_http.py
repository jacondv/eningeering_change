from odoo import models


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    def session_info(self):
        """Hands the web client the switches it applies itself - see
        static/src/debranding.js."""
        info = super().session_info()
        company = self.env.company
        info['jacon_debranding'] = {
            'hide_odoo_account': company.jacon_debranding_hidden('hide_odoo_account'),
            'hide_help': company.jacon_debranding_hidden('hide_help'),
            'tab_title': company.jacon_debranding_tab_title(),
        }
        return info
