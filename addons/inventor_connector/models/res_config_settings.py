import secrets

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    inventor_connector_api_key = fields.Char(
        string='Inventor API Key', config_parameter='inventor_connector.api_key',
        help="Shared secret Inventor scripts must send in the X-API-Key header "
             "when posting BOM data to /api/inventor/bom.")
    inventor_connector_max_payload_mb = fields.Float(
        string='Max Payload Size (MB)', config_parameter='inventor_connector.max_payload_mb', default=10.0,
        help="Reject incoming BOM requests larger than this size.")

    def action_regenerate_inventor_api_key(self):
        self.ensure_one()
        new_key = secrets.token_urlsafe(32)
        self.env['ir.config_parameter'].sudo().set_param('inventor_connector.api_key', new_key)
        return {'type': 'ir.actions.client', 'tag': 'reload'}
