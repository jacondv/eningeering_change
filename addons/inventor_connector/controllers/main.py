import json
import logging

from odoo import http
from odoo.exceptions import UserError
from odoo.http import request
from odoo.tools import consteq

_logger = logging.getLogger(__name__)


class InventorConnectorController(http.Controller):

    @http.route('/api/inventor/bom', type='http', auth='public', methods=['POST'], csrf=False)
    def import_bom(self, **kwargs):
        IrConfigParameter = request.env['ir.config_parameter'].sudo()

        max_payload_mb = float(IrConfigParameter.get_param('inventor_connector.max_payload_mb', '10') or 10)
        content_length = request.httprequest.content_length or 0
        if content_length > max_payload_mb * 1024 * 1024:
            return request.make_json_response(
                {'error': 'Payload too large (max %.1f MB).' % max_payload_mb}, status=413)

        expected_key = IrConfigParameter.get_param('inventor_connector.api_key')
        provided_key = request.httprequest.headers.get('X-API-Key', '')
        if not expected_key or not consteq(provided_key, expected_key):
            return request.make_json_response({'error': 'Invalid or missing API key.'}, status=401)

        try:
            payload = json.loads(request.httprequest.get_data(as_text=True) or '{}')
        except ValueError:
            return request.make_json_response({'error': 'Invalid JSON body.'}, status=400)

        try:
            bom = request.env['inventor.bom'].sudo()._upsert_from_payload(payload)
        except UserError as e:
            return request.make_json_response({'error': str(e)}, status=400)

        return request.make_json_response({'id': bom.id, 'model': bom.model, 'bom_type': bom.bom_type}, status=200)
