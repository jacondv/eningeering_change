import base64

from markupsafe import Markup, escape

from odoo import _, api, fields, models, tools
from odoo.exceptions import UserError

from . import office_placeholders
from .jacon_office_document import KINDS, MIMETYPES


class JaconOfficeTemplate(models.Model):
    """A company file (a Word, Excel or PowerPoint file with its theme, fonts, logo...) that new
    documents can start from. A new document is a copy of it; changing the document never changes it.

    A template has no Revs and no workflow: only its latest content matters. Editors add templates;
    changing one (its file included) is for Managers, since every new document starts from it.
    """
    _name = 'jacon.office.template'
    _description = 'Office Document Template'
    _order = 'sequence, name'

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    kind = fields.Selection(KINDS, required=True, readonly=True)
    category_id = fields.Many2one(
        'jacon.office.category',
        help="New documents of this category start from this template (when a category has several, the first).",
    )
    description = fields.Text()
    attachment_id = fields.Many2one('ir.attachment', string="Stored File", ondelete='set null', copy=False, readonly=True)
    file_size_text = fields.Char(string="Size", compute='_compute_file_size_text')
    # Only a way to hand the file over: it is moved into the filestore, as the template's file, when saved.
    upload = fields.Binary(string="File", attachment=False, copy=False)
    upload_filename = fields.Char(copy=False)

    # What the file's `{{placeholders}}` will be filled with, and what else can be used.
    placeholder_report = fields.Text(string="Placeholders", compute='_compute_placeholder_report')
    # The guide to writing them (the same for every template).
    placeholder_guide = fields.Html(compute='_compute_placeholder_guide', sanitize=False)
    # Whether the user may change this template (a new one, or they are a Manager).
    can_change = fields.Boolean(compute='_compute_can_change')

    _unique_name = models.UniqueIndex('(lower(name)) WHERE active', "A template with this name already exists.")

    @api.depends_context('uid')
    def _compute_can_change(self):
        is_manager = self.env.user.has_group('jacon_office.group_jacon_office_manager')
        for template in self:
            template.can_change = is_manager or not template.id

    @api.depends('name', 'kind')
    def _compute_display_name(self):
        kinds = dict(KINDS)
        for template in self:
            template.display_name = '%s (%s)' % (template.name, kinds[template.kind]) if template.kind else template.name

    @api.depends('attachment_id.checksum', 'kind')
    def _compute_placeholder_report(self):
        catalog = office_placeholders.CATALOG
        for template in self:
            attachment = template.sudo().attachment_id
            if not attachment:
                template.placeholder_report = ''
                continue
            if not office_placeholders.is_supported(template.kind):
                template.placeholder_report = _("Placeholders are filled in PowerPoint files only for now.")
                continue
            lines = []
            for name in sorted(office_placeholders.tokens_in(attachment.raw, template.kind)):
                if name in catalog:
                    lines.append('{{%s}}: OK' % name)
                elif '.' in name:
                    lines.append(_("{{%s}}: comes from the record the document belongs to (not checked here)", name))
                else:
                    lines.append(_("{{%s}}: UNKNOWN, it will stay as typed. Check its spelling.", name))
            template.placeholder_report = '\n'.join(lines) if lines else _("No placeholder in this file.")

    def _compute_placeholder_guide(self):
        def table(tokens):
            rows = Markup('').join(
                Markup('<tr><td><code>{{%s}}</code></td><td>%s</td><td class="text-muted">%s</td></tr>')
                % (name, _(label), example) for name, (label, example) in tokens.items()
            )
            return Markup(
                '<table class="table table-sm table-borderless mb-3"><thead><tr><th>%s</th><th>%s</th><th>%s</th>'
                '</tr></thead><tbody>%s</tbody></table>'
            ) % (_("Type"), _("Stands for"), _("Shows, for example"), rows)

        guide = Markup(
            '<p>%s</p><p class="fw-bold mb-1">%s</p><p class="text-muted mb-1">%s</p>%s'
            '<p class="fw-bold mb-1">%s</p><p class="text-muted mb-1">%s</p>%s'
            '<p class="text-muted">%s</p>'
        ) % (
            _("In the PowerPoint file, type a placeholder like {{rev}} in any text: a slide, the footer or the slide master."),
            _("Follow the workflow"),
            _("Filled in when the document is viewed, made into a PDF or downloaded. The file keeps the placeholder, so each Rev shows its own."),
            table(office_placeholders.WORKFLOW_TOKENS),
            _("Filled in once"),
            _("Written into the file when a document is made from this template; after that, change them by hand in the file."),
            table(office_placeholders.CREATION_TOKENS),
            _("A name that is not in these lists stays as typed: check the result below. Names ignore capitals and spaces inside the braces."),
        )
        for template in self:
            template.placeholder_guide = guide

    @api.depends('attachment_id.file_size')
    def _compute_file_size_text(self):
        for template in self:
            template.file_size_text = tools.human_size(template.attachment_id.file_size) if template.attachment_id else ''

    @api.onchange('upload_filename')
    def _onchange_upload_filename(self):
        self.kind = self.env['jacon.office.document']._kind_of_filename(self.upload_filename) or self.kind

    # ------------------------------------------------------------------
    # ORM
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [dict(vals) for vals in vals_list]
        for vals in vals_list:
            if not vals.get('upload'):
                raise UserError(_("Choose the file this template is made of."))
            kind = self.env['jacon.office.document']._kind_of_filename(vals.get('upload_filename'))
            if not kind:
                raise UserError(_("Only Word (.docx), Excel (.xlsx) and PowerPoint (.pptx) files can be templates."))
            vals['kind'] = kind
        templates = super().create(vals_list)
        templates._store_upload()
        return templates

    def write(self, vals):
        if 'kind' in vals and any(template.kind != vals['kind'] for template in self):
            raise UserError(_("The type of a template can't be changed: make a new one."))
        res = super().write(vals)
        if vals.get('upload'):
            self._store_upload()
        if 'name' in vals:
            for template in self.filtered('attachment_id'):
                template.attachment_id.sudo().name = template._attachment_filename()
        return res

    def unlink(self):
        attachments = self.attachment_id.sudo()
        res = super().unlink()
        attachments.exists().unlink()
        return res

    def _attachment_filename(self):
        self.ensure_one()
        return '%s.%s' % (self.env['jacon.office.document']._stem_of(self.name), self.kind)

    def _store_upload(self):
        """Make the handed-over file the template's file."""
        # Internal bookkeeping: an Editor may add a template but not change one, so this runs as superuser.
        for template in self.sudo().filtered('upload'):
            kind = self.env['jacon.office.document']._kind_of_filename(template.upload_filename)
            if kind != template.kind:
                raise UserError(_(
                    "This is not a %s file. A template's type can't change: make a new template instead.",
                    dict(KINDS)[template.kind],
                ))
            content = base64.b64decode(template.upload)
            self.env['jacon.office.document']._check_office_file(content, kind)
            values = {'raw': content, 'name': template._attachment_filename(), 'mimetype': MIMETYPES[kind]}
            if template.attachment_id:
                template.attachment_id.write(values)
            else:
                template.attachment_id = template.env['ir.attachment'].create(
                    dict(values, res_model=self._name, res_id=template.id)
                )
            template.write({'upload': False, 'upload_filename': False})

    def copy(self, default=None):
        """A copy has its own file (a template can't be saved without one) and a name of its own."""
        copies = self.browse()
        # The names in use: the ones the unique index is about (the active templates), compared as typed.
        taken = {name.lower() for name in self.search([]).mapped('name')}
        for template in self:
            if not template.attachment_id:
                raise UserError(_("This template has no file to copy."))
            name, number = _("%s (copy)", template.name), 1
            while name.lower() in taken:
                number += 1
                name = _("%(name)s (copy %(number)s)", name=template.name, number=number)
            values = dict(default or {}, name=name)
            values.setdefault('upload', base64.b64encode(template.attachment_id.sudo().raw))
            values.setdefault('upload_filename', template.attachment_id.name)
            copies |= self.create(dict(
                {field: template[field] for field in ('sequence', 'description')},
                category_id=template.category_id.id, **values,
            ))
            taken.add(values['name'].lower())
        return copies

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_open_editor(self):
        """Edit the template's file in ONLYOFFICE, in a new browser tab."""
        self.ensure_one()
        self.check_access('read')
        if not self.attachment_id:
            raise UserError(_("This template has no file."))
        return {'type': 'ir.actions.act_url', 'url': '/onlyoffice/editor/%s' % self.attachment_id.id, 'target': 'new'}

    def action_download(self):
        self.ensure_one()
        self.check_access('read')
        if not self.attachment_id:
            raise UserError(_("This template has no file."))
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s?download=true' % self.attachment_id.id,
            'target': 'self',
        }
