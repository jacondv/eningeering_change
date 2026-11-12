import io
import re
import zipfile
from collections import defaultdict

from odoo import _, api, fields, models, tools
from odoo.exceptions import AccessError, MissingError, UserError
from odoo.fields import Domain

KINDS = [('docx', 'Word'), ('xlsx', 'Excel'), ('pptx', 'PowerPoint')]

MIMETYPES = {
    'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
}

# The folder every genuine file of that kind has inside its zip container.
KIND_FOLDERS = {'docx': 'word/', 'xlsx': 'xl/', 'pptx': 'ppt/'}


class JaconOfficeDocument(models.Model):
    """A Word/Excel/PowerPoint file that belongs to another record.

    The file is an `ir.attachment` linked to this document (not to the record
    it belongs to, so it doesn't clutter that record's attachments). Who may
    read or change the document is decided by the record it belongs to, see
    `_check_access` and `_search`.
    """
    _name = 'jacon.office.document'
    _description = 'Office Document'
    _inherit = ['mail.thread']
    _order = 'id desc'

    name = fields.Char(required=True, tracking=True)
    kind = fields.Selection(KINDS, required=True)
    category_id = fields.Many2one('jacon.office.category', tracking=True)
    description = fields.Text()
    active = fields.Boolean(default=True)
    res_model = fields.Char(string="Belongs to (model)", required=True, index=True)
    res_id = fields.Many2oneReference(string="Belongs to (id)", model_field='res_model', required=True, index=True)
    res_name = fields.Char(string="Belongs to", compute='_compute_res_name')
    attachment_id = fields.Many2one('ir.attachment', string="File", ondelete='set null', copy=False, readonly=True)
    file_size_text = fields.Char(string="Size", compute='_compute_file_size_text')

    _unique_name_per_record = models.UniqueIndex(
        '(res_model, res_id, lower(name)) WHERE active',
        "This record already has a document with this name.",
    )

    @api.depends('res_model', 'res_id')
    def _compute_res_name(self):
        for doc in self:
            parent = self.env[doc.res_model].sudo().browse(doc.res_id) if doc.res_model in self.env else None
            doc.res_name = parent.exists().display_name if parent else ''

    @api.depends('attachment_id.file_size')
    def _compute_file_size_text(self):
        for doc in self:
            doc.file_size_text = tools.human_size(doc.attachment_id.file_size) if doc.attachment_id else ''

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

    def _attachment_filename(self):
        self.ensure_one()
        stem = re.sub(r'[\\/:*?"<>|]+', '-', self.name or '').strip() or _("Document")
        return '%s.%s' % (stem, self.kind)

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

    @api.model
    def _check_can_receive(self, res_model, res_id):
        parent = self.env[res_model].browse(res_id) if res_model in self.env else None
        if not parent or not parent.exists():
            raise UserError(_("The record this document belongs to no longer exists."))
        parent.check_access('write')
        if self._is_locked(parent):
            raise UserError(_("%s is locked: documents can no longer be added to it.", parent.display_name))

    @api.model
    def _is_locked(self, parent):
        """Whether the record (one of any model) has locked its documents. Only
        models using `jacon.office.mixin` can."""
        is_locked = getattr(parent, '_office_is_locked', None)
        return bool(is_locked and is_locked())

    def write(self, vals):
        if {'res_model', 'res_id'} & vals.keys():
            raise UserError(_("A document can't be moved to another record."))
        if 'kind' in vals and any(doc.kind != vals['kind'] for doc in self):
            raise UserError(_("The type of a document can't be changed."))
        res = super().write(vals)
        if 'name' in vals:
            for doc in self.filtered('attachment_id'):
                doc.attachment_id.sudo().name = doc._attachment_filename()
        return res

    def unlink(self):
        attachments = self.attachment_id.sudo()
        res = super().unlink()
        attachments.exists().unlink()
        return res

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_open_editor(self):
        """Open the file in the ONLYOFFICE editor, in a new browser tab."""
        self.ensure_one()
        self.check_access('read')
        if not self.attachment_id:
            raise UserError(_("This document has no file."))
        return {'type': 'ir.actions.act_url', 'url': self._editor_url(), 'target': 'new'}

    def _editor_url(self):
        self.ensure_one()
        return '/onlyoffice/editor/%s' % self.attachment_id.id

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
