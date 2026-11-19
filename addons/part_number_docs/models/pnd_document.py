import base64
import hashlib
import re
from urllib.parse import parse_qsl, quote, urlencode, urlsplit

from odoo import _, api, fields, models, tools
from odoo.exceptions import AccessError, UserError
from odoo.fields import Domain

GROUP_VIEW = 'part_number_docs.group_pnd_view'
GROUP_EDIT = 'part_number_docs.group_pnd_edit'
GROUP_MANAGE = 'part_number_docs.group_pnd_manage'

KINDS = [('file', "File"), ('link', "Link"), ('path', "Path"), ('note', "Note")]
SCOPES = ('all', 'part_number', 'part_description', 'vendor', 'vendor_ref', 'title', 'type', 'description')
PAGE_SIZE = 50
MAX_TERMS = 6  # words of a search that count
MAX_FACETS = 8  # chips of the search box that count
ROW_PARTS = 3  # part numbers a row of the list shows
PREVIEW_PARTS = 500  # part numbers the document panel lists (it shows five, the rest on request)

# What a file may be, told by its first bytes (the name and the declared type can lie):
# (the start of the file, the type to serve, the usual extension).
FILE_SIGNATURES = (
    (b'%PDF-', 'application/pdf', 'pdf'),
    (b'\x89PNG\r\n\x1a\n', 'image/png', 'png'),
    (b'\xff\xd8\xff', 'image/jpeg', 'jpg'),
    (b'GIF87a', 'image/gif', 'gif'),
    (b'GIF89a', 'image/gif', 'gif'),
)
# The Windows folder of the user: `C:\Users\<name>`.
WINDOWS_FOLDER_RE = re.compile(r'^[A-Za-z]:\\Users\\[^\\/:*?"<>|]+$')
BAD_PATH_CHARS = re.compile(r'[<>|*?"\x00-\x1f]')


# The letter SharePoint puts in the link of a file, by its kind.
SHARE_TYPES = {
    'pdf': 'b', 'doc': 'w', 'docx': 'w', 'xls': 'x', 'xlsx': 'x', 'ppt': 'p', 'pptx': 'p',
    'png': 'i', 'jpg': 'i', 'jpeg': 'i', 'gif': 'i', 'webp': 'i',
}


def share_encode(value):
    """A path as SharePoint writes it in a link: everything but letters and digits is percent-encoded."""
    return quote(value, safe='').replace('.', '%2E').replace('-', '%2D').replace('_', '%5F')


def sniff_file(content):
    """(mimetype, extension) of a PDF or image, or None for anything else."""
    for start, mimetype, extension in FILE_SIGNATURES:
        if content.startswith(start):
            return mimetype, extension
    if content[:4] == b'RIFF' and content[8:12] == b'WEBP':
        return 'image/webp', 'webp'
    return None


class PndDocument(models.Model):
    """A document of one or several part numbers: a datasheet, a manual, a drawing, a note...

    What it holds depends on its `kind`: a File stored here (PDF or image), a Link, a Path (kept
    relative to the folder OneDrive synchronises on every PC, so it is the same for everybody) or a Note.
    """
    _name = 'pnd.document'
    _description = 'Part Document'
    _inherit = ['mail.thread']
    _order = 'write_date desc, id desc'

    name = fields.Char(string="Title", required=True, index='trigram', tracking=True)
    type_id = fields.Many2one(
        'pnd.document.type', string="Type", required=True, ondelete='restrict', tracking=True,
        default=lambda self: self.env.ref('part_number_docs.type_datasheet', raise_if_not_found=False),
    )
    kind = fields.Selection(KINDS, string="Source", required=True, default='file', tracking=True)
    link_url = fields.Char(string="Link", index='trigram')
    rel_path = fields.Char(string="Path in the shared folder", index='trigram')
    note = fields.Html(string="Text")
    file = fields.Binary(string="File", attachment=True, copy=False)
    file_name = fields.Char(index='trigram')
    file_mimetype = fields.Char(copy=False, readonly=True)
    file_size_text = fields.Char(string="Size", compute='_compute_file_size_text')
    description = fields.Text(index='trigram')
    vendor_id = fields.Many2one('res.partner', string="Vendor", ondelete='set null')
    part_number_ids = fields.Many2many(
        'part_number_manager.part_number', 'pnd_document_part_rel', 'document_id', 'part_number_id',
        string="Part Numbers",
    )
    part_count = fields.Integer(compute='_compute_part_count')
    active = fields.Boolean(default=True, tracking=True)
    # What makes two documents "the same one" (a file's content, a link, a path): see `_key_of`.
    dedupe_key = fields.Char(index=True, copy=False, readonly=True)
    duplicate_id = fields.Many2one('pnd.document', compute='_compute_duplicate')
    duplicate_hint = fields.Char(compute='_compute_duplicate')

    # ------------------------------------------------------------------
    # Computed
    # ------------------------------------------------------------------

    @api.depends('file')
    def _compute_file_size_text(self):
        sizes = {
            attachment.res_id: attachment.file_size
            for attachment in self.env['ir.attachment'].sudo().search([
                ('res_model', '=', self._name), ('res_field', '=', 'file'), ('res_id', 'in', self.ids),
            ])
        }
        for doc in self:
            doc.file_size_text = tools.human_size(sizes[doc.id]) if doc.id in sizes else ''

    @api.depends('part_number_ids')
    def _compute_part_count(self):
        for doc in self:
            doc.part_count = len(doc.part_number_ids)

    @api.depends('kind', 'link_url', 'rel_path', 'file')
    def _compute_duplicate(self):
        """The form says so when what is being entered is a document that already exists."""
        keys = {}
        for doc in self:
            # A saved document read as it is has its key: nothing to hash. A form being filled in (the
            # record is virtual) is hashed from what was typed or chosen.
            keys[doc] = doc.dedupe_key if isinstance(doc.id, int) else doc._key_of(
                doc.kind, doc.link_url, doc.rel_path, doc.file)
        known = {key for key in keys.values() if key}
        found_by_key = {}
        if known:  # all the keys at once
            for other in self.env['pnd.document'].sudo().with_context(active_test=False).search(
                    [('dedupe_key', 'in', list(known))], order='id'):
                found_by_key.setdefault(other.dedupe_key, []).append(other)
        for doc in self:
            found = next((other for other in found_by_key.get(keys[doc], []) if other.id != doc._origin.id),
                         self.env['pnd.document'])
            doc.duplicate_id = found
            parts = ', '.join(found.part_number_ids[:5].mapped('part_number'))
            doc.duplicate_hint = _(
                "This is already in the system: \"%(name)s\"%(parts)s.",
                name=found.name, parts=_(" (for %s)", parts) if parts else '',
            ) if found else False

    # ------------------------------------------------------------------
    # The content: what is accepted, and what makes two documents the same
    # ------------------------------------------------------------------

    @api.model
    def _config(self):
        return self.env['pnd.config']._get()

    @api.model
    def _clean_link(self, url):
        """(the link as it will be kept, its key) - only web links are accepted."""
        url = (url or '').strip()
        parts = urlsplit(url)
        if parts.scheme.lower() not in ('http', 'https') or not parts.netloc or re.search(r'\s', url):
            raise UserError(_("A link must be a web address starting with http:// or https://"))
        query = urlencode([(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                           if not k.lower().startswith('utm_')])
        key = '%s://%s%s%s' % (parts.scheme, parts.netloc, parts.path.rstrip('/'), '?' + query if query else '')
        return url, key.lower()

    @api.model
    def _clean_path(self, raw):
        """The path kept for a file of the shared folder: what follows the synchronised folder's name
        (`C:\\Users\\Ann\\OneDrive - X\\Eng\\a.pdf` -> `Eng\\a.pdf`)."""
        raw = (raw or '').strip().strip('"').strip()
        root = self._config().sync_root_name
        path = raw.replace('/', '\\')
        marker = (root + '\\').casefold()
        position = path.casefold().find(marker)
        if position >= 0:
            path = path[position + len(marker):]
        elif re.match(r'^([A-Za-z]:|\\\\|%)', path):
            raise UserError(_(
                "This path is not inside the shared folder \"%s\". Copy the path of a file that is.", root))
        parts = [part.strip() for part in path.split('\\') if part.strip()]
        if not parts or any(part in ('.', '..') for part in parts) or BAD_PATH_CHARS.search(path):
            raise UserError(_("This is not a valid path of a file in the shared folder."))
        return '\\'.join(parts)

    @api.model
    def _key_of(self, kind, link_url, rel_path, file):
        """What tells that two documents are the same, or False (a note has none). Never raises: it is
        also asked while the form is being filled in."""
        try:
            if kind == 'file' and file:
                return 'file:' + hashlib.sha256(base64.b64decode(file)).hexdigest()
            if kind == 'link' and link_url:
                return 'link:' + self._clean_link(link_url)[1]
            if kind == 'path' and rel_path:
                return 'path:' + self._clean_path(rel_path).casefold()
        except (UserError, ValueError):
            pass
        return False

    def _prepare(self, vals, record=None):
        """The values to store: what the chosen `kind` needs is checked and cleaned, what belongs to
        the other kinds is dropped. `record` is the document being changed."""
        vals = dict(vals)
        if not ({'kind', 'link_url', 'rel_path', 'note', 'file', 'file_name'} & vals.keys()) and record:
            return vals
        kind = vals.get('kind') or (record.kind if record else 'file')

        def current(field):
            return vals[field] if field in vals else (record[field] if record else False)

        other = {'file': {'file', 'file_name', 'file_mimetype'}, 'link': {'link_url'}, 'path': {'rel_path'},
                 'note': {'note'}}
        for name, fields_ in other.items():
            if name != kind:
                vals.update({field: False for field in fields_})
        if kind == 'link':
            vals['link_url'], key = self._clean_link(current('link_url'))
            vals['dedupe_key'] = 'link:' + key
        elif kind == 'path':
            vals['rel_path'] = self._clean_path(current('rel_path'))
            vals['dedupe_key'] = 'path:' + vals['rel_path'].casefold()
        elif kind == 'note':
            if not tools.html2plaintext(current('note') or '').strip():
                raise UserError(_("Write the note."))
            vals['dedupe_key'] = False
        else:
            if vals.get('file'):
                content = base64.b64decode(vals['file'])
                found = sniff_file(content)
                if not found:
                    raise UserError(_("Only PDF files and images (PNG, JPG, GIF, WEBP) can be uploaded."))
                limit = self._config().max_file_mb
                if len(content) > limit * 1024 * 1024:
                    raise UserError(_("This file is larger than %s MB. Put it in the shared folder and add its path instead.", limit))
                vals['file_mimetype'] = found[0]
                vals['dedupe_key'] = 'file:' + hashlib.sha256(content).hexdigest()
                if not vals.get('file_name'):
                    vals['file_name'] = '%s.%s' % (vals.get('name') or (record.name if record else 'document'), found[1])
            elif 'file' in vals or not (record and record.kind == 'file' and record.file):
                raise UserError(_("Choose the file to upload."))
        return vals

    # ------------------------------------------------------------------
    # ORM
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        return super().create([self._prepare(vals) for vals in vals_list])

    def write(self, vals):
        if not ({'kind', 'link_url', 'rel_path', 'note', 'file', 'file_name'} & vals.keys()):
            return super().write(vals)
        for doc in self:
            super(PndDocument, doc).write(doc._prepare(vals, doc))
        return True

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_use_existing(self):
        """The document just entered already exists: its part numbers go to the existing one, and this
        copy is dropped."""
        self.ensure_one()
        self._check_group(GROUP_EDIT)
        self.check_access('write')
        existing = self.duplicate_id.sudo()
        if not existing:
            raise UserError(_("There is no existing document to use instead."))
        existing.part_number_ids |= self.sudo().part_number_ids
        existing.message_post(body=_("%(user)s added part numbers from a copy that was entered again.", user=self.env.user.name))
        self.sudo().unlink()
        return {
            'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': existing.id,
            'views': [(False, 'form')], 'target': 'current',
        }

    def action_open_merge(self):
        self._check_group(GROUP_EDIT)
        if len(self) < 2:
            raise UserError(_("Select at least two documents to merge."))
        return {
            'type': 'ir.actions.act_window',
            'name': _("Merge Documents"),
            'res_model': 'pnd.document.merge.wizard',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {'default_document_ids': [(6, 0, self.ids)], 'default_keep_id': self[:1].id},
        }

    @api.model
    def _check_group(self, group):
        if not self.env.su and not self.env.user.has_group(group):
            raise AccessError(_("You are not allowed to do this."))

    # ------------------------------------------------------------------
    # The search page
    # ------------------------------------------------------------------

    @api.model
    def _term_domain(self, scope, term):
        """The documents that have `term` in what `scope` covers."""
        # What is looked for in a part number (one sub-select on the part numbers, whatever the number of fields).
        by_scope_part = {
            'part_number': ['part_number', 'legacy_codes_display'],
            'part_description': ['short_description', 'long_description', 'display_description'],
            'vendor': ['vendor_id.name'],
            'vendor_ref': ['vendor_ref'],
        }
        by_scope_own = {
            'title': ['name', 'file_name'],
            'description': ['description', 'note'],
        }
        part_fields = by_scope_part.get(scope, [])
        own_fields = by_scope_own.get(scope, [])
        conditions = []
        if scope == 'all':
            part_fields = [field for names in by_scope_part.values() for field in names]
            own_fields = [field for names in by_scope_own.values() for field in names] + ['rel_path', 'link_url']
            conditions += [Domain('type_id', 'any', Domain('name', 'ilike', term))]
            conditions += [Domain('vendor_id', 'any', Domain('name', 'ilike', term))]
        elif scope == 'type':
            conditions += [Domain('type_id', 'any', Domain('name', 'ilike', term))]
        elif scope == 'vendor':
            conditions += [Domain('vendor_id', 'any', Domain('name', 'ilike', term))]
        conditions += [Domain(field, 'ilike', term) for field in own_fields]
        if part_fields:
            conditions.append(Domain('part_number_ids', 'any', Domain.OR(
                [Domain(field, 'ilike', term) for field in part_fields])))
        return Domain.OR(conditions)

    @api.model
    def search_documents(self, query='', scope='all', filters=None, offset=0, limit=PAGE_SIZE, facets=None):
        """What the search page lists: one row per document found, lightweight (no file is read).

        `facets` are the chips of the search box, [{'scope': ..., 'value': ...}]: all of them, and the
        free text `query`, have to match."""
        self._check_group(GROUP_VIEW)
        filters = filters or {}
        scope = scope if scope in SCOPES else 'all'
        domain = Domain.TRUE
        # Every word has to be found, each anywhere in the scope; the first few words only, so that a long
        # paste cannot make a huge query.
        searches = [(scope, query)]
        for facet in (facets or [])[:MAX_FACETS]:
            if isinstance(facet, dict) and facet.get('scope') in SCOPES:
                searches.append((facet['scope'], facet.get('value')))
        for facet_scope, text in searches:
            for term in (text or '').split()[:MAX_TERMS]:
                domain &= self._term_domain(facet_scope, term)
        if filters.get('type_ids'):  # several can be chosen: any of them
            domain &= Domain('type_id', 'in', [int(type_id) for type_id in filters['type_ids']])
        kinds = [kind for kind in filters.get('kinds') or [] if kind in dict(KINDS)]
        if kinds:
            domain &= Domain('kind', 'in', kinds)
        docs = self.sudo().with_context(active_test=not filters.get('archived'))
        if filters.get('archived'):
            domain &= Domain('active', '=', False)
        offset = int(offset)
        # The count is asked once, with the first page: the next pages don't recount.
        total = docs.search_count(domain) if not offset else None
        found = docs.search(domain, offset=offset, limit=min(int(limit), 200), order='name, id')
        found.mapped('file_size_text')  # computed for all the rows together, not one query per row
        parts = self._parts_summary(found.ids)
        return {'rows': [doc._row(parts.get(doc.id, ([], 0))) for doc in found], 'total': total}

    @api.model
    def _parts_summary(self, document_ids):
        """{document id: (its first part numbers, how many it has)} for these documents, in one query: a
        document of thousands of part numbers costs no more than a document of one."""
        if not document_ids:
            return {}
        self.env.cr.execute("""
            SELECT document_id, part_number, total FROM (
                SELECT r.document_id, p.part_number,
                       COUNT(*) OVER (PARTITION BY r.document_id) AS total,
                       ROW_NUMBER() OVER (PARTITION BY r.document_id ORDER BY p.part_number, p.id) AS position
                  FROM pnd_document_part_rel r
                  JOIN part_number_manager_part_number p ON p.id = r.part_number_id
                 WHERE r.document_id IN %s
            ) numbered WHERE position <= %s
        """, (tuple(document_ids), ROW_PARTS))
        summary = {}
        for document_id, part_number, total in self.env.cr.fetchall():
            names, _total = summary.setdefault(document_id, ([], total))
            names.append(part_number or '')
        return summary

    def _row(self, parts=([], 0)):
        """One row of the list; `parts` is (the first part numbers, how many there are)."""
        self.ensure_one()
        return {
            'id': self.id,
            'name': self.name,
            'type': self.type_id.name,
            'kind': self.kind,
            'extension': (self.file_name or '').rsplit('.', 1)[-1].lower() if self.kind == 'file' and self.file_name else '',
            'size': self.file_size_text,
            'vendor': self.vendor_id.name or '',
            'parts': parts[0],
            'part_count': parts[1],
            'author': self.create_uid.name,
            'date': fields.Date.to_string(self.write_date.date()) if self.write_date else '',
            'active': self.active,
        }

    @api.model
    def get_page_options(self):
        """What the search page needs to start: the types, and what the user may do."""
        self._check_group(GROUP_VIEW)
        user = self.env.user
        config = self._config()
        return {
            'types': [{'id': t.id, 'name': t.name} for t in self.env['pnd.document.type'].search([])],
            'kinds': [{'key': key, 'label': label} for key, label in KINDS],
            'can_edit': user.has_group(GROUP_EDIT),
            'can_manage': user.has_group(GROUP_MANAGE),
            'windows_folder': user.sudo().pnd_windows_folder or '',
            'root_name': config.sync_root_name,
            'default_type_id': self.env.ref('part_number_docs.type_datasheet').id,
        }

    def get_preview(self):
        """What the page shows for one document."""
        self.ensure_one()
        self._check_group(GROUP_VIEW)
        doc = self.sudo()
        folder = self.env.user.sudo().pnd_windows_folder
        root = self._config().sync_root_name
        result = dict(doc._row(self._parts_summary(doc.ids).get(doc.id, ([], 0))), **{
            'description': doc.description or '',
            'note': doc.note or '',
            'link_url': doc.link_url or '',
            'rel_path': doc.rel_path or '',
            'file_name': doc.file_name or '',
            'mimetype': doc.file_mimetype or '',
            'part_numbers': [{'id': p.id, 'name': p.part_number, 'description': p.short_description or ''}
                             for p in doc.part_number_ids.sorted('part_number')[:PREVIEW_PARTS]],
        })
        if doc.kind == 'path':
            result['web_url'] = doc._sharepoint_url()
            result['can_open'] = bool(result['web_url'] or folder)
            result['can_copy'] = bool(folder)
            result['copy_text'] = self._local_path(folder, root, doc.rel_path)
        return result

    def _sharepoint_url(self):
        """The address, on SharePoint, of the file this path names (or '' when SharePoint is not set up).

        The first folder of the path is the library as the PC shows it; what follows is inside the library,
        under the site. The link is of the kind SharePoint itself gives (`/:b:/r/site/library/Forms/AllItems.aspx?id=...`).
        """
        self.ensure_one()
        config = self._config()
        host = (config.sharepoint_url or '').strip().rstrip('/')
        site = '/' + (config.sharepoint_site or '').strip().strip('/')
        library = (config.sharepoint_library or '').strip().strip('/')
        parts = (self.rel_path or '').split('\\')
        if self.kind != 'path' or not host or not library or len(parts) < 2:
            return ''
        base = '%s/%s' % (site.rstrip('/'), library)
        inside = parts[1:]
        file_path = '%s/%s' % (base, '/'.join(inside))
        parent_path = '/'.join([base] + inside[:-1])
        kind = SHARE_TYPES.get(inside[-1].rsplit('.', 1)[-1].lower(), '')
        prefix = '/:%s:/r' % kind if kind else ''
        return '%s%s%s/Forms/AllItems.aspx?id=%s&parent=%s' % (
            host, prefix, quote(base, safe='/'), share_encode(file_path), share_encode(parent_path),
        )

    @api.model
    def _local_path(self, folder, root, rel_path):
        """The path of a file of the shared folder on the user's PC. Without their Windows folder it is
        written with %USERPROFILE%, which Explorer understands too."""
        return '%s\\%s\\%s' % (folder or '%USERPROFILE%', root, rel_path)

    def action_open(self):
        """Open the document in its own browser tab (a note opens in a window), for the buttons of lists."""
        self.ensure_one()
        self._check_group(GROUP_VIEW)
        doc = self.sudo()
        if doc.kind == 'file':
            url = '/web/content/pnd.document/%s/file/%s' % (doc.id, quote(doc.file_name or 'file'))
        elif doc.kind == 'link':
            url = doc.link_url
        elif doc.kind == 'path':
            web_url = doc._sharepoint_url()
            if web_url:
                return {'type': 'ir.actions.act_url', 'url': web_url, 'target': 'new'}
            folder = self.env.user.sudo().pnd_windows_folder
            if not folder:
                return {
                    'type': 'ir.actions.client', 'tag': 'display_notification',
                    'params': {
                        'title': _("Tell Odoo where your OneDrive is"),
                        'message': _("Open Documents > Part Documents, choose this document and write your Windows folder once."),
                        'type': 'warning', 'sticky': False,
                    },
                }
            # A browser doesn't open a file of the PC from a web page: the path goes to the clipboard,
            # to be pasted in the address bar.
            return {
                'type': 'ir.actions.client', 'tag': 'part_number_docs.open_path',
                'params': {'text': self._local_path(folder, self._config().sync_root_name, doc.rel_path)},
            }
        else:
            return {
                'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': doc.id,
                'views': [(False, 'form')], 'target': 'new',
            }
        return {'type': 'ir.actions.act_url', 'url': url, 'target': 'new'}

    @api.model
    def set_my_windows_folder(self, folder):
        """The user's own Windows folder (`C:\\Users\\Ann`), where their OneDrive lives."""
        self._check_group(GROUP_VIEW)
        folder = (folder or '').strip().strip('"').rstrip('\\/')
        if folder and not WINDOWS_FOLDER_RE.match(folder.replace('/', '\\')):
            raise UserError(_("Write it like C:\\Users\\YourName"))
        self.env.user.sudo().pnd_windows_folder = folder.replace('/', '\\') or False
        return self.env.user.sudo().pnd_windows_folder or ''
