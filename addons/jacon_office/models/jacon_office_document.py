import io
import json
import logging
import re
import time
import zipfile
from collections import defaultdict
from urllib.parse import quote

import requests

from odoo import SUPERUSER_ID, _, api, fields, models, tools
from odoo.exceptions import AccessError, MissingError, UserError
from odoo.fields import Domain

from odoo.addons.onlyoffice_odoo.utils import config_utils, jwt_utils, url_utils

_logger = logging.getLogger(__name__)

KINDS = [('docx', 'Word'), ('xlsx', 'Excel'), ('pptx', 'PowerPoint')]

MIMETYPES = {
    'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
}

# The folder every genuine file of that kind has inside its zip container.
KIND_FOLDERS = {'docx': 'word/', 'xlsx': 'xl/', 'pptx': 'ppt/'}

VERSIONS_TO_KEEP_PARAM = 'jacon_office.versions_to_keep'
DEFAULT_VERSIONS_TO_KEEP = 3
PDF_TIMEOUT = 90


class OfficeConversionError(Exception):
    """ONLYOFFICE could not turn the file into a PDF."""


class JaconOfficeDocument(models.Model):
    """A Word/Excel/PowerPoint file that belongs to another record.

    The file is an `ir.attachment` linked to this document (not to the record
    it belongs to, so it doesn't clutter that record's attachments). Who may
    read or change the document is decided by the record it belongs to, see
    `_check_access` and `_search`.

    Every time the file's content changes (ONLYOFFICE saved an edit, a Rev was
    restored) the previous content is kept as a Rev (`jacon.office.document.version`)
    and the PDF becomes out of date. It is made when someone asks to view it (most
    documents are never viewed as a PDF), then reused until the file changes again.
    """
    _name = 'jacon.office.document'
    _description = 'Office Document'
    _inherit = ['mail.thread']
    _order = 'id desc'

    name = fields.Char(required=True, tracking=True)
    kind = fields.Selection(KINDS, required=True)
    category_id = fields.Many2one('jacon.office.category', tracking=True)
    author_id = fields.Many2one(
        'res.users', string="Author", default=lambda self: self.env.user, ondelete='set null', tracking=True,
    )
    description = fields.Text()
    active = fields.Boolean(default=True)
    res_model = fields.Char(string="Belongs to (model)", required=True, index=True)
    res_id = fields.Many2oneReference(string="Belongs to (id)", model_field='res_model', required=True, index=True)
    res_name = fields.Char(string="Belongs to", compute='_compute_res_name')
    is_locked = fields.Boolean(compute='_compute_is_locked')

    attachment_id = fields.Many2one(
        'ir.attachment', string="File", ondelete='set null', copy=False, readonly=True, index=True,
    )
    file_size_text = fields.Char(string="Size", compute='_compute_file_size_text')
    # Rev N is the Nth content the file has had; the current content is the latest Rev.
    revision = fields.Integer(string="Rev", default=1, copy=False, readonly=True)
    last_edit_user_id = fields.Many2one('res.users', string="Last Edited By", copy=False, readonly=True, ondelete='set null')
    last_edit_date = fields.Datetime(string="Last Edited", copy=False, readonly=True)
    version_ids = fields.One2many('jacon.office.document.version', 'document_id', string="Previous Revs")
    version_count = fields.Integer(string="Previous Revs", compute='_compute_version_count', store=True)

    pdf_attachment_id = fields.Many2one('ir.attachment', string="PDF", ondelete='set null', copy=False, readonly=True)
    # The checksum of the file this PDF was made from: it is stale once the file's checksum differs.
    pdf_checksum = fields.Char(copy=False, readonly=True)
    pdf_state = fields.Selection(
        [('pending', "Not up to date"), ('ready', "Ready"), ('failed', "Failed")],
        string="PDF", default='pending', copy=False, readonly=True,
    )
    pdf_error = fields.Char(string="PDF Error", copy=False, readonly=True)

    _unique_name_per_record = models.UniqueIndex(
        '(res_model, res_id, lower(name)) WHERE active',
        "This record already has a document with this name.",
    )

    @api.depends('res_model', 'res_id')
    def _compute_res_name(self):
        ids_by_model = defaultdict(set)
        for doc in self:
            ids_by_model[doc.res_model].add(doc.res_id)
        names = {}
        for res_model, res_ids in ids_by_model.items():
            if res_model in self.env:
                for parent in self.env[res_model].sudo().browse(res_ids).exists():
                    names[(res_model, parent.id)] = parent.display_name
        for doc in self:
            doc.res_name = names.get((doc.res_model, doc.res_id), '')

    def _compute_is_locked(self):
        ids_by_model = defaultdict(set)
        for doc in self:
            ids_by_model[doc.res_model].add(doc.res_id)
        locked = set()
        for res_model, res_ids in ids_by_model.items():
            parents = self.env.get(res_model)
            if parents is not None:
                locked.update((res_model, parent.id) for parent in parents.browse(res_ids).exists() if self._is_locked(parent))
        for doc in self:
            doc.is_locked = (doc.res_model, doc.res_id) in locked

    @api.depends('attachment_id.file_size')
    def _compute_file_size_text(self):
        for doc in self:
            doc.file_size_text = tools.human_size(doc.attachment_id.file_size) if doc.attachment_id else ''

    @api.depends('version_ids')
    def _compute_version_count(self):
        for doc in self:
            doc.version_count = len(doc.sudo().version_ids)

    # ------------------------------------------------------------------
    # Access follows the record the document belongs to
    # ------------------------------------------------------------------

    def _check_access(self, operation):
        res = super()._check_access(operation)
        if self.env.su or not self:
            return res
        forbidden, error_func = res if res else (self.browse(), None)
        remaining = self - forbidden
        if not remaining:
            return res

        # Reading needs read access to the record; anything else needs write
        # access, and fails while the record is locked.
        parent_operation = 'read' if operation == 'read' else 'write'
        refs = {doc.id: (doc.res_model, doc.res_id) for doc in remaining.sudo()}
        ids_by_model = defaultdict(set)
        for res_model, res_id in refs.values():
            ids_by_model[res_model].add(res_id)

        blocked = set()
        for res_model, res_ids in ids_by_model.items():
            parents = self.env.get(res_model)
            if parents is None:
                blocked.update((res_model, res_id) for res_id in res_ids)
                continue
            parents = parents.browse(res_ids)
            try:
                allowed = parents._filtered_access(parent_operation)
            except MissingError:
                allowed = parents.exists()._filtered_access(parent_operation)
            if parent_operation == 'write':
                allowed = allowed.filtered(lambda parent: not self._is_locked(parent))
            blocked.update((res_model, res_id) for res_id in res_ids - set(allowed.ids))

        extra = self.browse([doc_id for doc_id, ref in refs.items() if ref in blocked])
        if not extra:
            return res
        if error_func is None:
            def error_func():
                return AccessError(self.env._(
                    "You are not allowed to access this document: the record it belongs to is "
                    "not accessible to you, or it is locked."
                ))
        return forbidden | extra, error_func

    @api.model
    def _search(self, domain, offset=0, limit=None, order=None, *, active_test=True, bypass_access=False):
        if self.env.su or bypass_access:
            return super()._search(domain, offset, limit, order, active_test=active_test, bypass_access=bypass_access)
        # Only the documents of records the user can read. A record counts even
        # when archived, like an attachment's record does.
        self.env.cr.execute("SELECT DISTINCT res_model FROM jacon_office_document")
        visible = []
        for (res_model,) in self.env.cr.fetchall():
            parents = self.env.get(res_model)
            if parents is None:
                continue
            try:
                query = parents._search(Domain.TRUE, active_test=False)
            except AccessError:
                continue
            visible.append(Domain('res_model', '=', res_model) & Domain('res_id', 'in', query))
        return super()._search(
            Domain(domain) & Domain.OR(visible), offset, limit, order, active_test=active_test,
        )

    @api.model
    def _is_locked(self, parent):
        """Whether the record (one of any model) has locked its documents. Only
        models using `jacon.office.mixin` can."""
        is_locked = getattr(parent, '_office_is_locked', None)
        return bool(is_locked and is_locked())

    @api.model
    def _check_can_receive(self, res_model, res_id):
        parent = self.env[res_model].browse(res_id) if res_model in self.env else None
        if not parent or not parent.exists():
            raise UserError(_("The record this document belongs to no longer exists."))
        parent.check_access('write')
        if self._is_locked(parent):
            raise UserError(_("%s is locked: documents can no longer be added to it.", parent.display_name))

    # ------------------------------------------------------------------
    # The file
    # ------------------------------------------------------------------

    @api.model
    def _blank_file(self, kind):
        with tools.file_open('jacon_office/data/templates/blank.%s' % kind, 'rb') as template:
            return template.read()

    @api.model
    def _check_office_file(self, content, kind):
        """Refuse anything that isn't a genuine file of that kind (a renamed zip, a PDF...)."""
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                names = archive.namelist()
        except zipfile.BadZipFile:
            names = []
        if '[Content_Types].xml' not in names or not any(n.startswith(KIND_FOLDERS[kind]) for n in names):
            raise UserError(_("This is not a valid %s file.", dict(KINDS)[kind]))

    def _stem(self):
        self.ensure_one()
        return re.sub(r'[\\/:*?"<>|]+', '-', self.name or '').strip() or _("Document")

    def _attachment_filename(self):
        return '%s.%s' % (self._stem(), self.kind)

    def _init_attachment(self, content=None):
        """Store the document's file: `content`, or a blank file of its kind."""
        self.ensure_one()
        if content is None:
            content = self._blank_file(self.kind)
        else:
            self._check_office_file(content, self.kind)
        self.attachment_id = self.env['ir.attachment'].sudo().create({
            'name': self._attachment_filename(),
            'raw': content,
            'mimetype': MIMETYPES[self.kind],
            'res_model': self._name,
            'res_id': self.id,
        })
        self.sudo().write({'last_edit_user_id': self.env.uid, 'last_edit_date': fields.Datetime.now()})

    # ------------------------------------------------------------------
    # Revs: the content a file had before it was last saved
    # ------------------------------------------------------------------

    @api.model
    def _versions_to_keep(self):
        value = self.env['ir.config_parameter'].sudo().get_param(VERSIONS_TO_KEEP_PARAM)
        try:
            return max(int(value), 0) if value not in (None, False, '') else DEFAULT_VERSIONS_TO_KEEP
        except ValueError:
            return DEFAULT_VERSIONS_TO_KEEP

    def _content_before_write(self):
        """What the file holds right now, to be compared once it was written."""
        keep = self._versions_to_keep()
        return {doc.id: (doc.attachment_id.checksum, doc.attachment_id.raw if keep else None) for doc in self}

    def _content_written(self, before):
        """The files of these documents were just written: if their content changed, keep the old
        content as a Rev, note who edited and mark the PDF as out of date."""
        for doc in self:
            checksum, old_content = before[doc.id]
            if doc.attachment_id.checksum == checksum:
                continue
            doc._keep_version(old_content, checksum)
            doc.write({
                'revision': doc.revision + 1,
                'last_edit_user_id': self.env.uid,
                'last_edit_date': fields.Datetime.now(),
                'pdf_state': 'pending',
                'pdf_error': False,
            })

    def _keep_version(self, content, checksum):
        self.ensure_one()
        keep = self._versions_to_keep()
        if keep:
            self.env['jacon.office.document.version'].sudo().create({
                'document_id': self.id,
                'number': self.revision,
                'user_id': self.last_edit_user_id.id,
                'date': self.last_edit_date,
                'checksum': checksum,
                'file_content': content,
            })
        self._trim_versions(keep)

    def _trim_versions(self, keep=None):
        """Drop the oldest Revs beyond the number to keep."""
        keep = self._versions_to_keep() if keep is None else keep
        for doc in self:
            doc.sudo().version_ids.sorted('number', reverse=True)[keep:].unlink()

    def _delete_old_versions(self):
        """Delete every previous Rev of these documents; return (how many, how many bytes)."""
        total_count = total_size = 0
        for doc in self:
            versions = doc.sudo().version_ids
            if not versions:
                continue
            count, size = len(versions), sum(versions.attachment_id.mapped('file_size'))
            doc.message_post(body=_(
                "%(user)s deleted %(count)s previous Revs (%(size)s freed).",
                user=self.env.user.name, count=count, size=tools.human_size(size),
            ))
            versions.unlink()
            total_count += count
            total_size += size
        return total_count, total_size

    # ------------------------------------------------------------------
    # The PDF
    # ------------------------------------------------------------------

    def _pdf_is_current(self):
        self.ensure_one()
        return bool(self.pdf_attachment_id and self.pdf_checksum == self.attachment_id.checksum)

    def _convert_to_pdf(self):
        """Make the PDF of the current file with ONLYOFFICE. Returns whether it worked; if not,
        the reason is kept in `pdf_error` (and the PDF stays what it was)."""
        self.ensure_one()
        doc = self.sudo()
        attachment = doc.attachment_id
        if not attachment:
            return False
        # The checksum of the content being converted: if the file is saved again meanwhile, the PDF
        # is then recognised as out of date (`_pdf_is_current`) rather than passed off as current.
        checksum = attachment.checksum
        try:
            content = doc._onlyoffice_convert(attachment, 'pdf')
        except Exception as error:  # a document the converter chokes on must not stop the others
            _logger.warning(
                "PDF of document %s (%s) failed: %s", doc.id, doc.name, error,
                exc_info=not isinstance(error, (OfficeConversionError, requests.RequestException)),
            )
            doc.write({'pdf_state': 'failed', 'pdf_error': str(error)[:250]})
            return False
        values = {
            'name': '%s.pdf' % doc._stem(), 'raw': content, 'mimetype': 'application/pdf',
            'res_model': self._name, 'res_id': doc.id,
        }
        if doc.pdf_attachment_id:
            doc.pdf_attachment_id.write(values)
        else:
            doc.pdf_attachment_id = self.env['ir.attachment'].sudo().create(values)
        doc.write({'pdf_state': 'ready', 'pdf_checksum': checksum, 'pdf_error': False})
        return True

    def _onlyoffice_convert(self, attachment, output_type):
        """Have ONLYOFFICE convert the attachment; returns the converted file's bytes.

        ONLYOFFICE fetches the file from Odoo itself (with a token naming the superuser), the
        same way it does to edit it, so the connector's settings (addresses, JWT) are what counts.
        """
        env = self.env
        odoo_url = config_utils.get_base_or_odoo_url(env)
        server_url = config_utils.get_doc_server_inner_url(env)
        secret = config_utils.get_jwt_secret(env)
        token = jwt_utils.encode_payload(env, {'id': SUPERUSER_ID}, config_utils.get_internal_jwt_secret(env))
        token = token.decode() if isinstance(token, bytes) else token
        # A key names one content: ONLYOFFICE reuses what it converted before for the same key. It
        # must differ from the editing session's key (`<id><checksum>`).
        key = 'pdf-%s-%s' % (attachment.id, attachment.checksum)
        body = {
            'async': False,
            'filetype': self.kind,
            'key': key,
            'outputtype': output_type,
            'title': attachment.name,
            'url': '%sonlyoffice/file/content/%s?oo_security_token=%s' % (odoo_url, attachment.id, token),
        }
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
        if secret:
            headers[config_utils.get_jwt_header(env)] = 'Bearer ' + jwt_utils.encode_payload(
                env, {'payload': dict(body)}, secret,
            )
            body['token'] = jwt_utils.encode_payload(env, dict(body), secret)
        verify = not config_utils.get_certificate_verify_disabled(env)

        deadline = time.monotonic() + PDF_TIMEOUT
        while True:
            response = requests.post(
                '%sconverter?shardkey=%s' % (server_url, key),
                data=json.dumps(body), headers=headers, verify=verify, timeout=PDF_TIMEOUT,
            )
            if response.status_code != 200:
                raise OfficeConversionError(_("ONLYOFFICE answered with status %s.", response.status_code))
            result = response.json()
            if result.get('error'):
                raise OfficeConversionError(_("ONLYOFFICE could not convert the file (error %s).", result['error']))
            if result.get('endConvert') and result.get('fileUrl'):
                break
            if time.monotonic() > deadline:
                raise OfficeConversionError(_("ONLYOFFICE took too long to convert the file."))
            time.sleep(2)
        download = requests.get(
            url_utils.replace_public_url_to_internal(env, result['fileUrl']), verify=verify, timeout=PDF_TIMEOUT,
        )
        if download.status_code != 200 or not download.content.startswith(b'%PDF'):
            raise OfficeConversionError(_("The converted PDF could not be downloaded."))
        return download.content

    # ------------------------------------------------------------------
    # ORM
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        """`file_content` (bytes) may be given with the values; without it the
        document starts as a blank file of its kind."""
        vals_list = [dict(vals) for vals in vals_list]
        contents = [vals.pop('file_content', None) for vals in vals_list]
        for vals in vals_list:
            self._check_can_receive(vals.get('res_model'), vals.get('res_id'))
        docs = super().create(vals_list)
        for doc, content in zip(docs, contents):
            doc._init_attachment(content)
        return docs

    def write(self, vals):
        if {'res_model', 'res_id'} & vals.keys():
            raise UserError(_("A document can't be moved to another record."))
        if 'kind' in vals and any(doc.kind != vals['kind'] for doc in self):
            raise UserError(_("The type of a document can't be changed."))
        res = super().write(vals)
        if 'name' in vals:
            for doc in self.filtered('attachment_id'):
                doc.attachment_id.sudo().name = doc._attachment_filename()
                if doc.pdf_attachment_id:
                    doc.pdf_attachment_id.sudo().name = '%s.pdf' % doc._stem()
        return res

    def unlink(self):
        # The Revs go with the document (database cascade), but not the files they hold.
        attachments = (self.attachment_id | self.pdf_attachment_id | self.sudo().version_ids.attachment_id).sudo()
        res = super().unlink()
        attachments.exists().unlink()
        return res

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _editor_url(self):
        self.ensure_one()
        return '/onlyoffice/editor/%s' % self.attachment_id.id

    def action_open_record(self):
        """Go to the record this document belongs to."""
        self.ensure_one()
        self.check_access('read')
        parent = self.env[self.res_model].browse(self.res_id) if self.res_model in self.env else None
        if not parent or not parent.exists():
            raise UserError(_("The record this document belongs to no longer exists."))
        parent.check_access('read')
        return {
            'type': 'ir.actions.act_window',
            'res_model': self.res_model,
            'res_id': self.res_id,
            'views': [(False, 'form')],
            'target': 'current',
        }

    def action_open_editor(self):
        """Open the file in the ONLYOFFICE editor, in a new browser tab."""
        self.ensure_one()
        self.check_access('read')
        if not self.attachment_id:
            raise UserError(_("This document has no file."))
        return {'type': 'ir.actions.act_url', 'url': self._editor_url(), 'target': 'new'}

    def action_view_pdf(self):
        """Show the document as a PDF, in a new browser tab; made now if it isn't up to date."""
        self.ensure_one()
        self.check_access('read')
        if not self.attachment_id:
            raise UserError(_("This document has no file."))
        if not self._pdf_is_current() and not self._convert_to_pdf():
            # Not an exception: it would roll back the failure just recorded.
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _("The PDF could not be created"),
                    'message': self.sudo().pdf_error,
                    'type': 'danger',
                    'sticky': True,
                },
            }
        pdf = self.sudo().pdf_attachment_id
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s/%s' % (pdf.id, quote(pdf.name)),
            'target': 'new',
        }

    def action_download(self):
        self.ensure_one()
        self.check_access('read')
        if not self.attachment_id:
            raise UserError(_("This document has no file."))
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s?download=true' % self.attachment_id.id,
            'target': 'self',
        }

    def action_view_versions(self):
        """A dialog listing the document's previous Revs."""
        self.ensure_one()
        self.check_access('read')
        user = self.last_edit_user_id.name
        return {
            'type': 'ir.actions.act_window',
            'name': _("%(name)s - current Rev %(rev)s", name=self.name, rev=self.revision)
                    + (_(" (saved by %s)", user) if user else ''),
            'res_model': 'jacon.office.document.version',
            'view_mode': 'list',
            'views': [(False, 'list')],
            'domain': [('document_id', '=', self.id)],
            'context': {'default_document_id': self.id},
            'target': 'new',
        }

    def action_delete_old_versions(self):
        """Delete every previous Rev of the documents (their current content is kept)."""
        self.check_access('write')
        count, size = self._delete_old_versions()
        message = (
            _("Deleted %(count)s previous Revs, freed %(size)s.", count=count, size=tools.human_size(size))
            if count else _("There was no previous Rev to delete.")
        )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'message': message, 'type': 'success' if count else 'info', 'sticky': False},
        }
