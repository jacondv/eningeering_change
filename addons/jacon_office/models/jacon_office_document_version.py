import json
import logging
from collections import defaultdict
from urllib.parse import quote

import requests

from odoo import _, api, fields, models, tools
from odoo.exceptions import AccessError, MissingError, UserError
from odoo.fields import Domain

from odoo.addons.onlyoffice_odoo.utils import config_utils, jwt_utils

from . import office_placeholders
from .jacon_office_document import OfficeConversionError, PDF_OUTPUT_TYPE, PDF_RETRY_AFTER, state_lock_skipped

_logger = logging.getLogger(__name__)

# The first key of the advisory lock that keeps a Rev from being converted twice at once.
REV_CONVERSION_LOCK_CLASS = 7313


class JaconOfficeDocumentVersion(models.Model):
    """A released Rev of a document: the content its file had when a Manager released it.

    Created by the document itself (never by users) when it is released. Who may
    see or delete one is decided by the document, so ultimately by the record it belongs to.
    (Documents from before the workflow also have Revs of the old kind: what the file held
    before each save. They are kept as history.)
    """
    _name = 'jacon.office.document.version'
    _description = 'Office Document Rev'
    _order = 'document_id, number desc'

    document_id = fields.Many2one('jacon.office.document', required=True, ondelete='cascade', index=True)
    number = fields.Integer(string="Rev", required=True)
    user_id = fields.Many2one('res.users', string="Released By", ondelete='set null')
    date = fields.Datetime(string="Released On")
    note = fields.Char(string="Reason", help="Why this Rev was made.")
    # The values of the file's placeholders when it was released (JSON); empty for older Revs.
    placeholder_values = fields.Text(copy=False)
    document_state = fields.Selection(related='document_id.state', string="Document State")
    checksum = fields.Char()
    attachment_id = fields.Many2one('ir.attachment', string="File", ondelete='set null', readonly=True)
    file_size_text = fields.Char(string="Size", compute='_compute_file_size_text')
    # Made the first time someone views it, and kept: a released Rev never changes.
    pdf_attachment_id = fields.Many2one('ir.attachment', string="PDF File", ondelete='set null', copy=False, readonly=True)
    pdf_error = fields.Char(copy=False, readonly=True)
    pdf_failed_date = fields.Datetime(copy=False, readonly=True)

    _unique_number = models.Constraint('UNIQUE (document_id, number)', "This Rev already exists.")

    @api.depends('attachment_id.file_size')
    def _compute_file_size_text(self):
        for version in self:
            version.file_size_text = tools.human_size(version.attachment_id.file_size) if version.attachment_id else ''

    # ------------------------------------------------------------------
    # Access follows the document
    # ------------------------------------------------------------------

    def _check_access(self, operation):
        res = super()._check_access(operation)
        if self.env.su or not self:
            return res
        forbidden, error_func = res if res else (self.browse(), None)
        remaining = self - forbidden
        if not remaining:
            return res
        document_of = {version.id: version.document_id.id for version in remaining.sudo()}
        allowed = self.env['jacon.office.document'].browse(set(document_of.values()))
        parent_operation = 'read' if operation == 'read' else 'write'
        # Deleting a Rev is not changing the document: it may be released.
        with state_lock_skipped(self.env):
            try:
                allowed = allowed._filtered_access(parent_operation)
            except MissingError:
                allowed = allowed.exists()._filtered_access(parent_operation)
        extra = self.browse([vid for vid, doc_id in document_of.items() if doc_id not in allowed.ids])
        if not extra:
            return res
        if error_func is None:
            def error_func():
                return AccessError(self.env._("You are not allowed to access this Rev."))
        return forbidden | extra, error_func

    @api.model
    def _search(self, domain, offset=0, limit=None, order=None, *, active_test=True, bypass_access=False):
        if self.env.su or bypass_access:
            return super()._search(domain, offset, limit, order, active_test=active_test, bypass_access=bypass_access)
        return super()._search(
            Domain(domain) & Domain('document_id', 'any', Domain.TRUE), offset, limit, order, active_test=active_test,
        )

    # ------------------------------------------------------------------
    # ORM
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        """`file_content` (bytes) is the content this Rev keeps."""
        vals_list = [dict(vals) for vals in vals_list]
        contents = [vals.pop('file_content', None) for vals in vals_list]
        versions = super().create(vals_list)
        for version, content in zip(versions, contents):
            doc = version.document_id
            version.attachment_id = self.env['ir.attachment'].sudo().create({
                'name': '%s Rev %s.%s' % (doc._stem(), version.number, doc.kind),
                'raw': content,
                'mimetype': doc.attachment_id.mimetype,
                'res_model': self._name,
                'res_id': version.id,
            })
        return versions

    def unlink(self):
        attachments = (self.attachment_id | self.pdf_attachment_id).sudo()
        res = super().unlink()
        attachments.exists().unlink()
        return res

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_download(self):
        self.ensure_one()
        self.check_access('read')
        return {
            'type': 'ir.actions.act_url',
            'url': '/jacon_office/rev/%s/download' % self.id,
            'target': 'self',
        }

    def action_view_pdf(self):
        """Show this Rev as a PDF in a new browser tab; made now the first time, then kept."""
        self.ensure_one()
        self.check_access('read')
        if not self.attachment_id:
            raise UserError(_("This Rev has no file."))
        if not self.pdf_attachment_id:
            failed = self.sudo().pdf_failed_date
            if failed and failed > fields.Datetime.now() - PDF_RETRY_AFTER:  # not at every click
                return self._notify(_("The PDF could not be created"), self.sudo().pdf_error, 'danger', sticky=True)
            self.env.cr.execute('SELECT pg_try_advisory_xact_lock(%s, %s)', (REV_CONVERSION_LOCK_CLASS, self.id))
            if not self.env.cr.fetchone()[0]:
                return self._notify(_("The PDF is being made"), _("Someone else just asked for it. Try again in a few seconds."), 'info')
            error = self._make_pdf()
            if error:
                return self._notify(_("The PDF could not be created"), error, 'danger', sticky=True)
        pdf = self.sudo().pdf_attachment_id
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s/%s' % (pdf.id, quote(pdf.name)),
            'target': 'new',
        }

    def _notify(self, title, message, kind, sticky=False):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'title': title, 'message': message, 'type': kind, 'sticky': sticky},
        }

    def _filled_token(self):
        """The token ONLYOFFICE presents to fetch the filled file of this Rev (and of no other)."""
        self.ensure_one()
        token = jwt_utils.encode_payload(
            self.env, {'jacon_office_rev': self.id}, config_utils.get_internal_jwt_secret(self.env),
        )
        return token.decode() if isinstance(token, bytes) else token

    def _make_pdf(self):
        """Convert this Rev's file with ONLYOFFICE; returns None, or why it could not be done."""
        self.ensure_one()
        rev = self.sudo()
        url = None
        if rev.placeholder_values:  # ONLYOFFICE is given the file with the values the Rev was released with
            url = '%sjacon_office/rev/%s/filled?oo_security_token=%s' % (
                config_utils.get_base_or_odoo_url(self.env), rev.id, rev._filled_token(),
            )
        try:
            content = rev.document_id._onlyoffice_convert(
                rev.attachment_id, PDF_OUTPUT_TYPE, key='%s-rev-%s' % (PDF_OUTPUT_TYPE, rev.id), url=url,
            )
        except Exception as error:  # a file the converter chokes on is told, not raised: nothing to roll back
            _logger.warning(
                "PDF of Rev %s of document %s failed: %s", rev.number, rev.document_id.id, error,
                exc_info=not isinstance(error, (OfficeConversionError, requests.RequestException)),
            )
            rev.write({'pdf_error': str(error)[:250], 'pdf_failed_date': fields.Datetime.now()})
            return str(error)[:250]
        rev.write({'pdf_error': False, 'pdf_failed_date': False})
        rev.pdf_attachment_id = self.env['ir.attachment'].sudo().create({
            'name': '%s Rev %s.pdf' % (rev.document_id._stem(), rev.number),
            'raw': content, 'mimetype': 'application/pdf',
            'res_model': self._name, 'res_id': rev.id,
        })
        return None

    def _download_file(self):
        """(file name, mimetype, content) of this Rev, its placeholders filled as they were when it was released."""
        self.ensure_one()
        self.check_access('read')
        attachment = self.sudo().attachment_id
        if not attachment:
            raise UserError(_("This Rev has no file."))
        content = attachment.raw
        values = self.sudo().placeholder_values
        if values:
            content = office_placeholders.fill(content, self.document_id.kind, json.loads(values))
        return attachment.name, attachment.mimetype, content

    def action_new_revision(self):
        """Open a new Rev of the document that starts from this Rev's content (asks why first)."""
        self.ensure_one()
        self.check_access('read')
        self.document_id.check_access('read')
        if not self.attachment_id:
            raise UserError(_("This Rev has no file."))
        return self.document_id._reason_wizard('new_rev', version=self)

    def action_delete(self):
        self.check_access('unlink')
        self.unlink()
