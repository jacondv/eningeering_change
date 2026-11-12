import base64
import os

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.jacon_office.models.jacon_office_document import KINDS


class JaconOfficeDocumentCreateWizard(models.TransientModel):
    _name = 'jacon.office.document.create.wizard'
    _description = 'New Office Document'

    res_model = fields.Char(required=True)
    res_id = fields.Many2oneReference(model_field='res_model', required=True)
    source = fields.Selection(
        [('new', "New blank file"), ('upload', "Upload an existing file")],
        default='new', required=True,
    )
    kind = fields.Selection(KINDS, default='docx')
    # A temporary value in the database, not a second copy of the file in the filestore.
    upload = fields.Binary(string="File", attachment=False)
    upload_filename = fields.Char()
    category_id = fields.Many2one(
        'jacon.office.category',
        default=lambda self: self.env.ref('jacon_office.category_specification', raise_if_not_found=False),
    )
    name = fields.Char(required=True)
    # The name suggested last, to tell a name the user typed from one we proposed.
    auto_name = fields.Char()
    description = fields.Text()

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        # The suggestion needs these even when the caller didn't ask for them.
        known = {**super().default_get(['res_model', 'res_id', 'category_id']), **res}
        suggestion = self._suggest_name(
            known.get('res_model'), known.get('res_id'),
            self.env['jacon.office.category'].browse(known.get('category_id')),
        )
        res.setdefault('name', suggestion)
        res['auto_name'] = suggestion
        return res

    @api.model
    def _suggest_name(self, res_model, res_id, category, upload_filename=None):
        """`<record name>-<category>`, or the uploaded file's name."""
        if upload_filename:
            name = os.path.splitext(upload_filename)[0]
        else:
            parent = self.env[res_model].browse(res_id) if res_model in self.env else None
            parent_name = parent.exists().display_name if parent else ''
            suffix = category.name or _("Document")
            name = '%s-%s' % (parent_name, suffix) if parent_name else suffix
        # A record can't have two documents of the same name: number the new one.
        taken = {
            doc.name.lower() for doc in self.env['jacon.office.document'].sudo().search([
                ('res_model', '=', res_model), ('res_id', '=', res_id),
            ])
        } if res_model and res_id else set()
        candidate, number = name, 1
        while candidate.lower() in taken:
            number += 1
            candidate = '%s (%s)' % (name, number)
        return candidate

    @api.onchange('upload_filename')
    def _onchange_upload_filename(self):
        extension = os.path.splitext(self.upload_filename or '')[1].lstrip('.').lower()
        if extension in dict(KINDS):
            self.kind = extension

    @api.onchange('source', 'category_id', 'upload_filename')
    def _onchange_suggest_name(self):
        suggestion = self._suggest_name(
            self.res_model, self.res_id, self.category_id,
            self.upload_filename if self.source == 'upload' else None,
        )
        if not self.name or self.name == self.auto_name:
            self.name = suggestion
        self.auto_name = suggestion

    def _create_document(self):
        self.ensure_one()
        content = None
        kind = self.kind
        if self.source == 'upload':
            if not self.upload:
                raise UserError(_("Choose the file to upload."))
            kind = os.path.splitext(self.upload_filename or '')[1].lstrip('.').lower()
            if kind not in dict(KINDS):
                raise UserError(_("Only Word (.docx), Excel (.xlsx) and PowerPoint (.pptx) files can be uploaded."))
            content = base64.b64decode(self.upload)
        return self.env['jacon.office.document'].create({
            'name': self.name,
            'kind': kind,
            'category_id': self.category_id.id,
            'description': self.description,
            'res_model': self.res_model,
            'res_id': self.res_id,
            'file_content': content,
        })

    def action_create(self):
        self._create_document()
        return {'type': 'ir.actions.act_window_close'}

    def action_create_and_edit(self):
        """Create the document, then open it in the editor and close this dialog."""
        doc = self._create_document()
        return {
            'type': 'ir.actions.client',
            'tag': 'jacon_office_open_editor',
            'params': {'url': doc._editor_url()},
        }
