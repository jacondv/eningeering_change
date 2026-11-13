import hashlib
import io
import json
import logging
import os
import re
import time
from contextlib import contextmanager
import zipfile
from collections import defaultdict
from datetime import datetime
from urllib.parse import quote

import requests

from odoo import SUPERUSER_ID, _, api, fields, models, tools
from odoo.exceptions import AccessError, MissingError, UserError
from odoo.fields import Domain

from odoo.addons.onlyoffice_odoo.utils import config_utils, jwt_utils, url_utils

from . import office_placeholders

_logger = logging.getLogger(__name__)

KINDS = [('docx', 'Word'), ('xlsx', 'Excel'), ('pptx', 'PowerPoint')]

MIMETYPES = {
    'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
}

# The folder every genuine file of that kind has inside its zip container.
KIND_FOLDERS = {'docx': 'word/', 'xlsx': 'xl/', 'pptx': 'ppt/'}

GROUP_MANAGER = 'jacon_office.group_jacon_office_manager'
# While set, a document that is no longer a Draft may still be moved along the workflow or archived
# (`state_lock_skipped`). It lives on the cursor, not in the context: a client can send any context.
STATE_LOCK_KEY = 'jacon_office_skip_state_lock'


@contextmanager
def state_lock_skipped(env):
    env.cr.cache[STATE_LOCK_KEY] = env.cr.cache.get(STATE_LOCK_KEY, 0) + 1
    try:
        yield
    finally:
        env.cr.cache[STATE_LOCK_KEY] -= 1


def _state_lock_is_skipped(env):
    return bool(env.cr.cache.get(STATE_LOCK_KEY))


# Only the workflow's own actions (which run with elevated rights) change these.
WORKFLOW_FIELDS = frozenset({
    'state', 'revision', 'revision_reason', 'reject_reason',
    'submitted_by_id', 'submitted_date', 'approved_by_id', 'approved_date',
})

PDF_TIMEOUT = 90
# The first key of the advisory lock that keeps a document from being converted twice at once.
CONVERSION_LOCK_CLASS = 7312
MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
# PDF/A, not plain PDF: ONLYOFFICE writes gradient fills of plain PDFs in a way many viewers draw wrongly
# (shapes lost or smeared), while its PDF/A shows them right.
PDF_OUTPUT_TYPE = 'pdfa'


class OfficeConversionError(Exception):
    """ONLYOFFICE could not turn the file into a PDF."""


class JaconOfficeDocument(models.Model):
    """A Word/Excel/PowerPoint file that belongs to another record.

    The file is an `ir.attachment` linked to this document (not to the record
    it belongs to, so it doesn't clutter that record's attachments). Who may
    read or change the document is decided by the record it belongs to, see
    `_check_access` and `_search`.

    A document is a Draft (the file is edited in place: closing the editor saves it, no Rev
    is made), then Submitted for review, then Released by a Manager. Releasing keeps the file
    as a Rev (`jacon.office.document.version`) and locks the document. To change it, someone
    opens a new Rev, which is a Draft again, and the released Revs stay available.

    Whenever the file's content changes the PDF becomes out of date. It is made when someone
    asks to view it (most documents are never viewed as a PDF), then reused until the file
    changes again.
    """
    _name = 'jacon.office.document'
    _description = 'Office Document'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    # Commenting on a released document must stay possible: it is locked for writing.
    _mail_post_access = 'read'

    name = fields.Char(required=True, tracking=True)
    kind = fields.Selection(KINDS, required=True)
    category_id = fields.Many2one('jacon.office.category', tracking=True)
    # Free text: the author can be someone who is not a user. The tab suggests the users' names.
    author = fields.Char(default=lambda self: self.env.user.name, tracking=True)
    description = fields.Text()
    active = fields.Boolean(default=True)
    res_model = fields.Char(string="Belongs to (model)", required=True, index=True)
    res_id = fields.Many2oneReference(string="Belongs to (id)", model_field='res_model', required=True, index=True)
    res_name = fields.Char(string="Belongs to", compute='_compute_res_name')
    is_locked = fields.Boolean(compute='_compute_is_locked')
    # What the screens enable or disable (the server decides again on every action):
    # - can_edit: the user may change the document now: it is a Draft and they may write its record,
    #   which is not locked.
    # - can_work: they may move it along (submit, recall, open a new Rev, archive): as above, in any state.
    # - can_approve: it is waiting for review and they are a Manager.
    can_edit = fields.Boolean(compute='_compute_access_flags')
    can_work = fields.Boolean(compute='_compute_access_flags')
    can_approve = fields.Boolean(compute='_compute_access_flags')

    state = fields.Selection(
        [('draft', "Draft"), ('review', "In Review"), ('released', "Released")],
        default='draft', required=True, index=True, copy=False, readonly=True, tracking=True,
    )

    attachment_id = fields.Many2one(
        'ir.attachment', string="File", ondelete='set null', copy=False, readonly=True, index=True,
    )
    file_size_text = fields.Char(string="Size", compute='_compute_file_size_text')
    # The Rev being worked on (Draft, In Review) or the one released.
    revision = fields.Integer(string="Rev", default=1, copy=False, readonly=True)
    revision_reason = fields.Char(string="Reason for this Rev", copy=False, readonly=True)
    reject_reason = fields.Text(string="Rejected Because", copy=False, readonly=True)
    submitted_by_id = fields.Many2one('res.users', string="Submitted By", copy=False, readonly=True, ondelete='set null')
    submitted_date = fields.Datetime(string="Submitted On", copy=False, readonly=True)
    approved_by_id = fields.Many2one('res.users', string="Released By", copy=False, readonly=True, ondelete='set null')
    approved_date = fields.Datetime(string="Released On", copy=False, readonly=True)
    last_edit_user_id = fields.Many2one('res.users', string="Last Edited By", copy=False, readonly=True, ondelete='set null')
    last_edit_date = fields.Datetime(string="Last Edited", copy=False, readonly=True)
    version_ids = fields.One2many('jacon.office.document.version', 'document_id', string="Revs")
    version_count = fields.Integer(string="Released Revs", compute='_compute_version_count', store=True)

    pdf_attachment_id = fields.Many2one('ir.attachment', string="PDF File", ondelete='set null', copy=False, readonly=True)
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

    @api.depends_context('uid')
    @api.depends('state', 'res_model', 'res_id')
    def _compute_access_flags(self):
        # The only difference between the two is the state, so the (costly) access check runs once.
        with state_lock_skipped(self.env):
            workable = self.filtered('id')._filtered_access('write')
        is_manager = self.env.user.has_group(GROUP_MANAGER)
        for doc in self:
            doc.can_work = doc in workable
            doc.can_edit = doc.can_work and doc.state == 'draft'
            doc.can_approve = is_manager and doc.state == 'review'

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
        # Only a Draft can be changed (the files of the others included: ONLYOFFICE then opens them read-only).
        if operation == 'write' and not _state_lock_is_skipped(self.env):
            extra |= remaining.filtered(lambda doc: doc.sudo().state != 'draft')
        if not extra:
            return res
        if error_func is None:
            def error_func():
                return AccessError(self.env._(
                    "You can't change this document: it is not a Draft, or the record it belongs to "
                    "is locked or not accessible to you."
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

    @api.model
    def _kind_of_filename(self, filename):
        """'docx', 'xlsx' or 'pptx' for such a file name, else None."""
        extension = os.path.splitext(filename or '')[1].lstrip('.').lower()
        return extension if extension in dict(KINDS) else None

    @api.model
    def _stem_of(self, name):
        """A name made safe to be a file's name."""
        return re.sub(r'[\\/:*?"<>|]+', '-', name or '').strip() or _("Document")

    def _stem(self):
        self.ensure_one()
        return self._stem_of(self.name)

    def _attachment_filename(self):
        return '%s.%s' % (self._stem(), self.kind)

    def _init_attachment(self, content=None):
        """Store the document's file: `content`, or a blank file of its kind."""
        self.ensure_one()
        if content is None:
            content = self._blank_file(self.kind)
        else:
            self._check_office_file(content, self.kind)
            if office_placeholders.is_supported(self.kind):
                content = office_placeholders.fill(content, self.kind, self._creation_values())
        self.attachment_id = self.env['ir.attachment'].sudo().create({
            'name': self._attachment_filename(),
            'raw': content,
            'mimetype': MIMETYPES[self.kind],
            'res_model': self._name,
            'res_id': self.id,
        })
        self.sudo().write({'last_edit_user_id': self.env.uid, 'last_edit_date': fields.Datetime.now()})

    # ------------------------------------------------------------------
    # The content changed
    # ------------------------------------------------------------------

    def _content_written(self, checksums):
        """The files of these documents were just written (ONLYOFFICE saved an edit): for those
        whose content changed, note who edited and make the PDF out of date.
        `checksums` are what the files held before."""
        for doc in self:
            if doc.attachment_id.checksum != checksums[doc.id]:
                doc.write({
                    'last_edit_user_id': self.env.uid,
                    'last_edit_date': fields.Datetime.now(),
                    'pdf_state': 'pending',
                    'pdf_error': False,
                })

    # ------------------------------------------------------------------
    # Revs: what was released
    # ------------------------------------------------------------------

    def _delete_old_versions(self):
        """Delete every released Rev of these documents but the latest; return (how many, how many bytes)."""
        total_count = total_size = 0
        for doc in self:
            versions = doc.sudo().version_ids.sorted('number')[:-1]
            if not versions:
                continue
            count, size = len(versions), sum(versions.attachment_id.mapped('file_size'))
            doc.message_post(body=_(
                "%(user)s deleted %(count)s older Revs (%(size)s freed).",
                user=self.env.user.name, count=count, size=tools.human_size(size),
            ))
            versions.unlink()
            total_count += count
            total_size += size
        return total_count, total_size

    # ------------------------------------------------------------------
    # The workflow: Draft -> In Review -> Released -> (new Rev) Draft
    # ------------------------------------------------------------------

    def _log(self, body, notify=None):
        """Note what happened in the chatter of the document and of the record it belongs to (so that
        whoever follows the Project sees it); `notify` are the users who are told about it."""
        self.ensure_one()
        partners = notify.partner_id if notify else self.env['res.partner']
        if partners:
            self.message_post(body=body, partner_ids=partners.ids, subtype_xmlid='mail.mt_comment')
        else:
            self.message_post(body=body)
        parent = self.env[self.res_model].sudo().browse(self.res_id) if self.res_model in self.env else None
        if parent and parent.exists() and hasattr(parent, 'message_post'):
            parent.message_post(
                body=_("Document %(name)s: %(what)s", name=self.name, what=body),
                author_id=self.env.user.partner_id.id,
            )

    def _check_state(self, state):
        for doc in self:
            if doc.state != state:
                raise UserError(_(
                    "%(name)s must be %(state)s for this.",
                    name=doc.name, state=dict(self._fields['state'].selection)[state],
                ))

    def _check_can_work(self):
        """The user may move these documents along, whatever their state."""
        with state_lock_skipped(self.env):
            self.check_access('write')

    def _check_is_approver(self):
        if not self.env.user.has_group(GROUP_MANAGER):
            raise AccessError(_("Only a Manager can approve or reject a document."))
        self.check_access('read')

    def _approvers(self):
        return self.env.ref(GROUP_MANAGER).sudo().all_user_ids.filtered(lambda user: user.active and not user.share)

    def action_submit(self):
        """Send the Draft to the Managers for review; it can't be changed meanwhile."""
        self._check_can_work()
        self._check_state('draft')
        approvers = self._approvers()
        for doc in self:
            if not doc.attachment_id:
                raise UserError(_("%s has no file.", doc.name))
            if doc._editor_is_open():
                raise UserError(_(
                    "%s is still open in the editor. Close its tab, wait about 10 seconds so that what you "
                    "typed reaches Odoo, then submit it.", doc.name,
                ))
        for doc in self.sudo():
            doc.write({
                'state': 'review', 'reject_reason': False,
                'submitted_by_id': self.env.uid, 'submitted_date': fields.Datetime.now(),
            })
            doc._log(
                _("%(user)s submitted Rev %(rev)s for review.", user=self.env.user.name, rev=doc.revision),
                notify=approvers,
            )
            for approver in approvers:
                doc.activity_schedule(
                    'mail.mail_activity_data_todo', user_id=approver.id,
                    summary=_("Review %(name)s (Rev %(rev)s)", name=doc.name, rev=doc.revision),
                )
        return True

    def action_recall(self):
        """Take a document back from review to change it."""
        self._check_can_work()
        self._check_state('review')
        for doc in self.sudo():
            doc.write({'state': 'draft'})
            doc.activity_unlink(['mail.mail_activity_data_todo'])
            doc._log(_("%(user)s took Rev %(rev)s back from review.", user=self.env.user.name, rev=doc.revision))
        return True

    def action_reject(self, reason):
        """A Manager sends the document back to Draft, saying why."""
        self._check_is_approver()
        self._check_state('review')
        reason = (reason or '').strip()
        if not reason:
            raise UserError(_("Say why the document is rejected."))
        for doc in self.sudo():
            doc.write({'state': 'draft', 'reject_reason': reason})
            doc.activity_unlink(['mail.mail_activity_data_todo'])
            doc._log(
                _("%(user)s rejected Rev %(rev)s: %(reason)s", user=self.env.user.name, rev=doc.revision, reason=reason),
                notify=doc.submitted_by_id,
            )
        return True

    def action_approve(self):
        """A Manager releases the document: its file is kept as a Rev and it can no longer be changed."""
        self._check_is_approver()
        self._check_state('review')
        for doc in self.sudo():
            doc.write({'state': 'released', 'approved_by_id': self.env.uid, 'approved_date': fields.Datetime.now()})
            self.env['jacon.office.document.version'].sudo().create({
                'document_id': doc.id,
                'number': doc.revision,
                'user_id': self.env.uid,
                'date': doc.approved_date,
                'note': doc.revision_reason or _("First release"),
                'checksum': doc.attachment_id.checksum,
                'file_content': doc.attachment_id.raw,
                # What its placeholders said at release: this Rev always downloads as it was released.
                'placeholder_values': json.dumps(doc._placeholder_values()),
            })
            doc.activity_unlink(['mail.mail_activity_data_todo'])
            doc._log(
                _("%(user)s released Rev %(rev)s.", user=self.env.user.name, rev=doc.revision),
                notify=doc.submitted_by_id,
            )
        return True

    def action_new_revision(self, reason, version=None):
        """Open a new Rev of a released document: a Draft that starts from the released file, or from
        the content of an older `version`. The released Revs stay as they are."""
        self.ensure_one()
        self._check_can_work()
        self._check_state('released')
        reason = (reason or '').strip()
        if not reason:
            raise UserError(_("Say why a new Rev is needed."))
        doc = self.sudo()
        if version:
            if version.document_id != doc:
                raise UserError(_("That Rev belongs to another document."))
            if not version.attachment_id:
                raise UserError(_("This Rev has no file."))
            if version.checksum != doc.attachment_id.checksum:
                doc.attachment_id.write({'raw': version.attachment_id.sudo().raw})
        number = max(doc.version_ids.mapped('number') + [doc.revision]) + 1
        doc.write({'state': 'draft', 'revision': number, 'revision_reason': reason, 'reject_reason': False})
        # The Managers are told: a released document is being changed.
        doc._log(_(
            "%(user)s opened Rev %(rev)s%(source)s: %(reason)s", user=self.env.user.name, rev=number, reason=reason,
            source=_(" from Rev %s", version.number) if version else '',
        ), notify=self._approvers())
        return True

    def _reason_wizard(self, mode, version=None):
        self.ensure_one()
        self.check_access('read')
        return {
            'type': 'ir.actions.act_window',
            'name': _("Reject") if mode == 'reject' else _("New Rev"),
            'res_model': 'jacon.office.document.reason.wizard',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {
                'default_document_id': self.id, 'default_mode': mode,
                'default_version_id': version.id if version else False,
            },
        }

    def action_ask_reject(self):
        return self._reason_wizard('reject')

    def action_ask_new_revision(self):
        return self._reason_wizard('new_rev')

    # ------------------------------------------------------------------
    # Placeholders: {{rev}}, {{author}}... in the file, filled when it is shown
    # ------------------------------------------------------------------

    @api.model
    def _format_date(self, value):
        """12-Aug-2026 (the month in English whatever the language: it is a document's text)."""
        if not value:
            return ''
        if isinstance(value, datetime):
            value = fields.Datetime.context_timestamp(self, value)
        return '%02d-%s-%d' % (value.day, MONTHS[value.month - 1], value.year)

    def _creation_values(self):
        """The placeholders that are filled once, when the document is made: they are written into its
        file then (a template's `{{author}}`...), and from there people change them by hand."""
        self.ensure_one()
        doc = self.sudo()
        return {
            'category': doc.category_id.name,
            'author': doc.author,
            'description': doc.description,
            'belongs_to': doc.res_name,
            'company': self.env.company.name,
        }

    def _placeholder_values(self):
        """What each placeholder stands for now (names in lower case). The record the document
        belongs to can add its own, see `jacon.office.mixin._office_placeholders`."""
        self.ensure_one()
        doc = self.sudo()
        values = {
            'rev': doc.revision,
            'state': dict(self._fields['state'].selection)[doc.state],
            'released_by': doc.approved_by_id.name,
            'released_date': self._format_date(doc.approved_date),
            'submitted_by': doc.submitted_by_id.name,
            'last_edit_by': doc.last_edit_user_id.name,
            'last_edit_date': self._format_date(doc.last_edit_date),
        }
        parent = self.env[doc.res_model].sudo().browse(doc.res_id) if doc.res_model in self.env else None
        extra = parent._office_placeholders() if parent and parent.exists() and hasattr(parent, '_office_placeholders') else {}
        values.update({name.lower(): value for name, value in extra.items()})
        return {name: '' if value in (False, None) else value for name, value in values.items()}

    def _placeholders_used(self):
        """The placeholders in the file, or an empty set (no need to read anything but the file)."""
        self.ensure_one()
        attachment = self.sudo().attachment_id
        if not attachment or not office_placeholders.is_supported(self.kind):
            return set()
        # A content never changes under its checksum: what was found in it is kept for the rest of the request.
        cache_key = ('jacon_office_placeholders', attachment.checksum)
        if cache_key not in self.env.cr.cache:
            self.env.cr.cache[cache_key] = office_placeholders.tokens_in(attachment.raw, self.kind)
        return self.env.cr.cache[cache_key]

    def _render_key(self):
        """Names what is shown of the file: its content, and the values of the placeholders it has. The
        PDF is current as long as this is the same (a Rev, or the day, changing nothing a file shows
        leaves it be)."""
        self.ensure_one()
        checksum = self.sudo().attachment_id.checksum
        used = self._placeholders_used()
        if not used:
            return checksum
        values = self._placeholder_values()
        shown = json.dumps({name: str(values[name]) for name in sorted(used) if name in values})
        return hashlib.sha1(('%s%s' % (checksum, shown)).encode()).hexdigest()

    def _filled_content(self, values=None):
        """The file with its placeholders filled in, or None when it has none (use the stored file)."""
        self.ensure_one()
        attachment = self.sudo().attachment_id
        if not attachment or not office_placeholders.is_supported(self.kind):
            return None
        if not self._placeholders_used():
            return None
        return office_placeholders.fill(
            attachment.raw, self.kind, values if values is not None else self._placeholder_values(),
        )

    # ------------------------------------------------------------------
    # The PDF
    # ------------------------------------------------------------------

    def _pdf_is_current(self):
        self.ensure_one()
        return bool(self.pdf_attachment_id and self.pdf_checksum == self._render_key())

    def _take_conversion_lock(self):
        """Whether this request may convert the document: the lock lasts until its transaction ends."""
        self.ensure_one()
        self.env.cr.execute('SELECT pg_try_advisory_xact_lock(%s, %s)', (CONVERSION_LOCK_CLASS, self.id))
        return self.env.cr.fetchone()[0]

    def _convert_to_pdf(self):
        """Make the PDF of the current file with ONLYOFFICE. Returns whether it worked; if not,
        the reason is kept in `pdf_error` (and the PDF stays what it was)."""
        self.ensure_one()
        doc = self.sudo()
        attachment = doc.attachment_id
        if not attachment:
            return False
        # What is being converted (the file and the values its placeholders show): if either changes
        # meanwhile, the PDF is then recognised as out of date (`_pdf_is_current`) rather than passed off as current.
        try:
            checksum = doc._render_key()
            content = doc._onlyoffice_convert(attachment, PDF_OUTPUT_TYPE)
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

    def _onlyoffice_sign(self, body):
        """The headers and the body to send ONLYOFFICE, signed with the connector's JWT secret."""
        env = self.env
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
        secret = config_utils.get_jwt_secret(env)
        if secret:
            headers[config_utils.get_jwt_header(env)] = 'Bearer ' + jwt_utils.encode_payload(
                env, {'payload': dict(body)}, secret,
            )
            body = dict(body, token=jwt_utils.encode_payload(env, dict(body), secret))
        return headers, body

    def _editor_is_open(self):
        """Whether someone has this document open in the editor right now.

        What they type reaches Odoo only when the last of them closes it (and a few seconds after), so
        the file here, and the PDF made from it, can be behind what they see.
        """
        self.ensure_one()
        env = self.env
        key = '%s%s' % (self.attachment_id.id, self.attachment_id.checksum)  # the connector's editing key
        try:
            headers, body = self._onlyoffice_sign({'c': 'info', 'key': key})
            response = requests.post(
                '%scoauthoring/CommandService.ashx' % config_utils.get_doc_server_inner_url(env),
                data=json.dumps(body), headers=headers, timeout=3,
                verify=not config_utils.get_certificate_verify_disabled(env),
            )
            result = response.json()
        except (requests.RequestException, ValueError):
            return False  # unknown: say nothing rather than something wrong
        return result.get('error') == 0 and bool(result.get('users'))

    def _onlyoffice_convert(self, attachment, output_type, key=None, url=None):
        """Have ONLYOFFICE convert the attachment; returns the converted file's bytes.

        ONLYOFFICE fetches the file from Odoo itself (with a token naming the superuser), the
        same way it does to edit it, so the connector's settings (addresses, JWT) are what counts.
        """
        env = self.env
        odoo_url = config_utils.get_base_or_odoo_url(env)
        server_url = config_utils.get_doc_server_inner_url(env)
        token = jwt_utils.encode_payload(env, {'id': SUPERUSER_ID}, config_utils.get_internal_jwt_secret(env))
        token = token.decode() if isinstance(token, bytes) else token
        # A key names one content: ONLYOFFICE reuses what it converted before for the same key. It
        # must differ from the editing session's key (`<id><checksum>`), and it follows what the file
        # shows (see `_render_key`), not only the file.
        # (`key` and `url` are given for a file that is not the document's current one, a Rev's.)
        key = key or '%s-%s-%s' % (output_type, attachment.id, self._render_key())
        url = url or '%sonlyoffice/file/content/%s?oo_security_token=%s' % (odoo_url, attachment.id, token)
        if url.startswith('%sonlyoffice/' % odoo_url) and attachment == self.attachment_id and self._placeholders_used():
            # ONLYOFFICE is given the file with its placeholders filled in: Odoo fills them as the
            # file is fetched, so no copy is stored anywhere.
            url = '%sjacon_office/document/%s/filled?oo_security_token=%s' % (
                odoo_url, self.id, self._filled_token(),
            )
        body = {
            'async': False,
            'filetype': self.kind,
            'key': key,
            'outputtype': output_type,
            'title': attachment.name,
            'url': url,
        }
        headers, body = self._onlyoffice_sign(body)
        verify = not config_utils.get_certificate_verify_disabled(env)

        deadline = time.monotonic() + PDF_TIMEOUT
        while True:
            response = requests.post(
                '%sconverter?shardkey=%s' % (server_url, key),
                data=json.dumps(body), headers=headers, verify=verify,
                timeout=max(5, deadline - time.monotonic()),  # the whole wait stays within PDF_TIMEOUT
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
            if not self.env.su:  # a document starts as a Draft: the workflow's fields aren't for users to set
                for field in WORKFLOW_FIELDS & vals.keys():
                    del vals[field]
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
        if not self.env.su:
            if WORKFLOW_FIELDS & vals.keys():
                raise UserError(_("The state and the Rev of a document change through the workflow's buttons only."))
            if (_state_lock_is_skipped(self.env) and not vals.keys() <= {'active'}
                    and any(doc.state != 'draft' for doc in self)):
                raise UserError(_("Only a Draft can be changed."))
        res = super().write(vals)
        if 'name' in vals:
            for doc in self.filtered('attachment_id'):
                doc.attachment_id.sudo().name = doc._attachment_filename()
                if doc.pdf_attachment_id:
                    doc.pdf_attachment_id.sudo().name = '%s.pdf' % doc._stem()
        return res

    def action_archive(self):
        # Archiving is allowed in any state (see `write`).
        with state_lock_skipped(self.env):
            return super().action_archive()

    def action_unarchive(self):
        with state_lock_skipped(self.env):
            return super().action_unarchive()

    def unlink(self):
        # The Revs go with the document (database cascade), but not the files they hold.
        versions = self.sudo().version_ids
        attachments = (self.attachment_id | self.pdf_attachment_id | versions.attachment_id | versions.pdf_attachment_id).sudo()
        res = super().unlink()
        attachments.exists().unlink()
        return res

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _editor_url(self):
        """Where the file opens in ONLYOFFICE. A document that can't be changed now, and has
        placeholders, opens as a view of the filled file (nothing is saved from it); any other opens
        the stored file, for editing if the user may."""
        self.ensure_one()
        if not self.can_edit and self._placeholders_used():
            return '/jacon_office/document/%s/view' % self.id
        return '/onlyoffice/editor/%s' % self.attachment_id.id

    def action_open_form(self):
        """The document's own form: its details and its history in the chatter."""
        self.ensure_one()
        self.check_access('read')
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'views': [(False, 'form')],
            'target': 'current',
        }

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
        if not self._pdf_is_current():
            if not self._take_conversion_lock():
                # Someone asked for this very PDF a moment ago: don't make it twice.
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _("The PDF is being made"),
                        'message': _("Someone else just asked for it. Try again in a few seconds."),
                        'type': 'info',
                    },
                }
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
        if self._editor_is_open():
            self.env['bus.bus']._sendone(self.env.user.partner_id, 'simple_notification', {
                'type': 'warning',
                'title': _("%s is open in the editor", self.name),
                'message': _(
                    "The PDF shows the last version saved to Odoo. What is typed in the editor reaches Odoo "
                    "when the editor's tab is closed: close it, wait about 10 seconds, then view the PDF again."
                ),
                'sticky': True,
            })
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
            'url': '/jacon_office/document/%s/download' % self.id,
            'target': 'self',
        }

    def _filled_token(self):
        """The token ONLYOFFICE presents to fetch the filled file of this document (and of no other)."""
        self.ensure_one()
        token = jwt_utils.encode_payload(
            self.env, {'jacon_office_document': self.id}, config_utils.get_internal_jwt_secret(self.env),
        )
        return token.decode() if isinstance(token, bytes) else token

    def action_download_original(self):
        """The file as stored, placeholders (`{{rev}}`...) not filled: the one to change and put back."""
        self.ensure_one()
        self.check_access('read')
        if not self.attachment_id:
            raise UserError(_("This document has no file."))
        return {
            'type': 'ir.actions.act_url',
            'url': '/jacon_office/document/%s/download?original=1' % self.id,
            'target': 'self',
        }

    def action_ask_replace_file(self):
        self.ensure_one()
        self.check_access('write')
        return {
            'type': 'ir.actions.act_window',
            'name': _("Replace File"),
            'res_model': 'jacon.office.document.replace.wizard',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {'default_document_id': self.id},
        }

    def action_replace_file(self, content, filename=None):
        """Put `content` (the file's bytes) in place of the file of this Draft."""
        self.ensure_one()
        self.check_access('write')  # a Draft only, and only whoever may change its record
        if not self.attachment_id:
            raise UserError(_("This document has no file."))
        if filename and self._kind_of_filename(filename) not in (None, self.kind):
            raise UserError(_("This document is %s: choose a file of the same type.", dict(KINDS)[self.kind]))
        self._check_office_file(content, self.kind)
        if self._editor_is_open():
            raise UserError(_(
                "%s is still open in the editor. Close its tab, wait about 10 seconds so that what was "
                "typed reaches Odoo, then replace the file.", self.name,
            ))
        # The attachment's write hook notes who changed the file and makes the PDF out of date.
        self.sudo().attachment_id.raw = content
        self._log(_("%(user)s replaced the file of %(name)s.", user=self.env.user.name, name=self.name))
        return True

    def _download_file(self, original=False):
        """(file name, mimetype, content) of what a download gives: the file with its placeholders filled,
        or as stored when `original`."""
        self.ensure_one()
        self.check_access('read')
        attachment = self.sudo().attachment_id
        if not attachment:
            raise UserError(_("This document has no file."))
        if original:
            return attachment.name, attachment.mimetype, attachment.raw
        filled = self._filled_content()
        return attachment.name, attachment.mimetype, attachment.raw if filled is None else filled

    def action_view_versions(self):
        """A dialog listing the document's released Revs."""
        self.ensure_one()
        self.check_access('read')
        return {
            'type': 'ir.actions.act_window',
            'name': _("%(name)s - Revs (now Rev %(rev)s, %(state)s)", name=self.name, rev=self.revision,
                      state=dict(self._fields['state'].selection)[self.state]),
            'res_model': 'jacon.office.document.version',
            'view_mode': 'list',
            'views': [(False, 'list')],
            'domain': [('document_id', '=', self.id)],
            'context': {'default_document_id': self.id},
            'target': 'new',
        }

    def action_delete_old_versions(self):
        """Delete every released Rev of the documents but the latest."""
        self._check_can_work()
        self.env['jacon.office.document.version'].check_access('unlink')
        count, size = self._delete_old_versions()
        message = (
            _("Deleted %(count)s older Revs, freed %(size)s.", count=count, size=tools.human_size(size))
            if count else _("There was no older Rev to delete.")
        )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'message': message, 'type': 'success' if count else 'info', 'sticky': False},
        }
