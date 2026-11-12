from collections import defaultdict

from odoo import _, api, fields, models, tools
from odoo.exceptions import AccessError, MissingError, UserError
from odoo.fields import Domain


class JaconOfficeDocumentVersion(models.Model):
    """A previous Rev of a document: the content its file had before it was last saved.

    Created by the document itself (never by users) whenever its file changes. Who may
    see or delete one is decided by the document, so ultimately by the record it belongs to.
    """
    _name = 'jacon.office.document.version'
    _description = 'Office Document Rev'
    _order = 'document_id, number desc'

    document_id = fields.Many2one('jacon.office.document', required=True, ondelete='cascade', index=True)
    number = fields.Integer(string="Rev", required=True)
    user_id = fields.Many2one('res.users', string="Saved By", ondelete='set null')
    date = fields.Datetime(string="Saved On")
    checksum = fields.Char()
    attachment_id = fields.Many2one('ir.attachment', string="File", ondelete='set null', readonly=True)
    file_size_text = fields.Char(string="Size", compute='_compute_file_size_text')

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
        try:
            allowed = allowed._filtered_access('read' if operation == 'read' else 'write')
        except MissingError:
            allowed = allowed.exists()._filtered_access('read' if operation == 'read' else 'write')
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
        attachments = self.attachment_id.sudo()
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
            'url': '/web/content/%s?download=true' % self.attachment_id.id,
            'target': 'self',
        }

    def action_restore(self):
        """Make this Rev the document's current content again. What the document held until now
        becomes a Rev of its own, so nothing is lost."""
        self.ensure_one()
        self.check_access('read')
        doc = self.document_id
        doc.check_access('write')
        if not self.attachment_id:
            raise UserError(_("This Rev has no file."))
        if not doc._versions_to_keep():
            raise UserError(_(
                "Revs are not kept (Settings > Office Documents), so restoring this one would lose the "
                "document's current content. Download this Rev instead, or keep at least one Rev."
            ))
        doc.attachment_id.sudo().write({'raw': self.attachment_id.sudo().raw})
        doc.message_post(body=_("%(user)s restored Rev %(rev)s.", user=self.env.user.name, rev=self.number))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'message': _("Rev %s is the current content again.", self.number),
                'type': 'success',
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    def action_delete(self):
        self.check_access('unlink')
        self.unlink()
