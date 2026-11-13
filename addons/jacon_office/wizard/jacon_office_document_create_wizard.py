import base64
import os

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.jacon_office.models import office_placeholders
from odoo.addons.jacon_office.models.jacon_office_document import KINDS


class JaconOfficeDocumentCreateWizard(models.TransientModel):
    _name = 'jacon.office.document.create.wizard'
    _description = 'New Office Document'

    res_model = fields.Char(required=True)
    res_id = fields.Many2oneReference(model_field='res_model', required=True)
    # What the file starts from, in this order: an uploaded file, a template, else a blank file of `kind`.
    kind = fields.Selection(KINDS, string="Type", default='pptx')
    template_id = fields.Many2one('jacon.office.template', string="Template")
    # The template proposed for the category, and whether the user has chosen one (or Blank) themselves:
    # a choice of theirs is not replaced when the category changes.
    auto_template_id = fields.Many2one('jacon.office.template')
    template_chosen = fields.Boolean()
    # What the chosen template fills in by itself, so that nobody retypes it.
    template_tokens = fields.Char(compute='_compute_template_tokens')
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

    @api.depends('template_id')
    def _compute_template_tokens(self):
        for wizard in self:
            attachment = wizard.template_id.sudo().attachment_id
            found = office_placeholders.tokens_in(attachment.raw, wizard.template_id.kind) if (
                attachment and office_placeholders.is_supported(wizard.template_id.kind)) else set()
            known = [name for name in office_placeholders.CATALOG if name in found]
            wizard.template_tokens = _("This template fills in: %s", ', '.join(known)) if known else False

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
        # A category with a template starts from it.
        template = self._template_of(self.env['jacon.office.category'].browse(known.get('category_id')))
        if template and not {'default_template_id', 'default_kind'} & set(self.env.context):
            res['template_id'] = res['auto_template_id'] = template.id
        return res

    @api.model
    def _template_of(self, category):
        return self.env['jacon.office.template'].search([('category_id', '=', category.id)], limit=1) if category else None

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

    @api.onchange('upload')
    def _onchange_upload(self):
        # A file chosen to upload is the start: no template, and its type is the file's own.
        if self.upload:
            self.template_id = False
            self.template_chosen = True
            self.kind = self.env['jacon.office.document']._kind_of_filename(self.upload_filename) or self.kind

    @api.onchange('template_id')
    def _onchange_template(self):
        if self.template_id:
            self.upload = False
            self.upload_filename = False
        if self.template_id != self.auto_template_id:
            self.template_chosen = True

    @api.onchange('category_id')
    def _onchange_category_template(self):
        """The category's template is proposed, unless the user chose what to start from (or uploaded a file)."""
        if self.template_chosen or self.upload:
            return
        self.template_id = self.auto_template_id = self._template_of(self.category_id)

    @api.onchange('upload', 'upload_filename', 'category_id')
    def _onchange_suggest_name(self):
        suggestion = self._suggest_name(
            self.res_model, self.res_id, self.category_id,
            self.upload_filename if self.upload else None,
        )
        if not self.name or self.name == self.auto_name:
            self.name = suggestion
        self.auto_name = suggestion

    def _create_document(self):
        self.ensure_one()
        content = None
        kind = self.kind
        if self.upload:
            kind = self.env['jacon.office.document']._kind_of_filename(self.upload_filename)
            if not kind:
                raise UserError(_("Only Word (.docx), Excel (.xlsx) and PowerPoint (.pptx) files can be uploaded."))
            content = base64.b64decode(self.upload)
        elif self.template_id:
            kind = self.template_id.kind
            content = self.template_id.attachment_id.sudo().raw
            if not content:
                raise UserError(_("The template %s has lost its file. Choose another one.", self.template_id.name))
        elif not kind:
            raise UserError(_("Choose the type of file to create."))
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
