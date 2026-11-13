import json
import logging

import jwt
import markupsafe
from werkzeug.exceptions import NotFound

from odoo import http
from odoo.http import content_disposition, request

from odoo.addons.onlyoffice_odoo.controllers.controllers import Onlyoffice_Connector
from odoo.addons.onlyoffice_odoo.utils import config_utils, jwt_utils


_logger = logging.getLogger(__name__)


class JaconOfficeController(http.Controller):
    """Downloads of the files of documents, with their placeholders filled in."""

    def _send(self, record, original=False):
        if not record:
            raise NotFound()
        name, mimetype, content = record._download_file(original=True) if original else record._download_file()
        return request.make_response(content, headers=[
            ('Content-Type', mimetype),
            ('Content-Length', len(content)),
            ('Content-Disposition', content_disposition(name)),
        ])

    @http.route('/jacon_office/document/<int:document_id>/download', type='http', auth='user')
    def download_document(self, document_id, original=None):
        """`?original=1`: the file as stored, with its placeholders, to be changed and put back."""
        return self._send(request.env['jacon.office.document'].browse(document_id).exists(), original=bool(original))

    @http.route('/jacon_office/document/<int:document_id>/filled', type='http', auth='public')
    def filled_document(self, document_id, oo_security_token=None):
        """What ONLYOFFICE fetches to make the PDF: the file with its placeholders filled in. It
        is not for people (they have the download above), so it asks for the token only
        `document._filled_token` gives, which names this document."""
        env = request.env
        try:
            payload = jwt_utils.decode_token(env, oo_security_token or '', config_utils.get_internal_jwt_secret(env))
        except jwt.PyJWTError:
            raise NotFound()
        if payload.get('jacon_office_document') != document_id:
            raise NotFound()
        return self._send(env['jacon.office.document'].sudo().browse(document_id).exists())

    @http.route('/jacon_office/document/<int:document_id>/view', type='http', auth='user')
    def view_document(self, document_id):
        """The editor, for viewing only, on the file with its placeholders filled in (what the PDF and
        the download show). Nothing is saved from it: there is no callback."""
        env = request.env
        doc = env['jacon.office.document'].browse(document_id).exists()
        if not doc:
            raise NotFound()
        doc.check_access('read')
        attachment = doc.attachment_id
        if not attachment:
            raise NotFound()
        try:
            values = self._filled_view_values(doc, attachment)
        except (KeyError, TypeError, AttributeError):
            # The connector's page is not what this was written for (it was upgraded?): the stored file
            # opens instead, with its placeholders unfilled, rather than nothing.
            _logger.exception("The viewer of the filled document %s could not be prepared", doc.id)
            return request.redirect('/onlyoffice/editor/%s' % attachment.id)
        return request.render('onlyoffice_odoo.onlyoffice_editor', values)

    def _filled_view_values(self, doc, attachment):
        """What the connector's editor page is given, for viewing the filled file. This leans on the
        connector's `prepare_editor_values` (its keys: `editorConfig`, `docApiJS`, `session_info`)."""
        env = request.env
        values = Onlyoffice_Connector().prepare_editor_values(attachment, None, False)
        config = values['editorConfig']
        old_key = config['document']['key']
        new_key = 'view-%s-%s' % (doc.id, doc._render_key())
        config['document']['key'] = new_key
        config['document']['url'] = '%sjacon_office/document/%s/filled?oo_security_token=%s' % (
            config_utils.get_base_or_odoo_url(env), doc.id, doc._filled_token(),
        )
        config['editorConfig'].pop('callbackUrl', None)
        for stale in ('token', 'iat', 'exp'):  # signed again below, now that the document differs
            config.pop(stale, None)
        if jwt_utils.is_jwt_enabled(env):
            config['token'] = jwt_utils.encode_payload(env, config)
        if old_key not in values['docApiJS']:
            raise KeyError('docApiJS')  # the editor would load under another key than the one signed
        values['docApiJS'] = values['docApiJS'].replace(old_key, new_key)
        values['editorConfig'] = markupsafe.Markup(json.dumps(config))
        values['session_info'] = markupsafe.Markup(json.dumps(values['session_info']))
        return values

    @http.route('/jacon_office/rev/<int:version_id>/filled', type='http', auth='public')
    def filled_rev(self, version_id, oo_security_token=None):
        """What ONLYOFFICE fetches to make the PDF of a Rev: its file with the values it was released with.
        Asks for the token only `version._filled_token` gives, which names this Rev."""
        env = request.env
        try:
            payload = jwt_utils.decode_token(env, oo_security_token or '', config_utils.get_internal_jwt_secret(env))
        except jwt.PyJWTError:
            raise NotFound()
        if payload.get('jacon_office_rev') != version_id:
            raise NotFound()
        return self._send(env['jacon.office.document.version'].sudo().browse(version_id).exists())

    @http.route('/jacon_office/rev/<int:version_id>/download', type='http', auth='user')
    def download_rev(self, version_id):
        return self._send(request.env['jacon.office.document.version'].browse(version_id).exists())
