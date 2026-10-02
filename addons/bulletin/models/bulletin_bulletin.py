from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import html2plaintext


class Bulletin(models.Model):
    _name = 'bulletin.bulletin'
    _description = 'Bulletin'
    _inherit = ['mail.thread']
    _order = 'id desc'

    name = fields.Char(
        string='Document Number', required=True, copy=False, readonly=True,
        default=lambda self: 'New')
    template_id = fields.Many2one('bulletin.template', required=True, tracking=True)
    date = fields.Date(default=fields.Date.context_today)
    version = fields.Char(default='01')
    user_id = fields.Many2one('res.users', string='Responsible', default=lambda self: self.env.user)
    section_ids = fields.One2many('bulletin.bulletin.section', 'bulletin_id', string='Sections', copy=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)
    active = fields.Boolean(default=True)

    _name_uniq = models.Constraint('unique(name)', 'This Document Number already exists.')

    @api.onchange('template_id')
    def _onchange_template_id(self):
        for rec in self:
            # Only auto-populate the first time a Template is picked - once the
            # author has started filling sections in, switching Template again
            # must not silently wipe everything they already typed.
            if rec.section_ids:
                continue
            lines = [(0, 0, {
                'section_id': tsec.section_id.id,
                'template_section_id': tsec.id,
                'approver_id': (tsec.default_approver_id or self.env.user.employee_id).id,
                'content': tsec.section_id.default_value,
            }) for tsec in rec.template_id.section_ids.sorted('sequence')]
            rec.section_ids = [(5, 0, 0)] + lines

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals['name'] == 'New':
                vals['name'] = self._generate_document_number()
        return super().create(vals_list)

    def _generate_document_number(self):
        # Backed by a real ir.sequence (one per month, auto-created on first
        # use) instead of "highest existing record name + 1" - a counter
        # keeps counting up even after a Bulletin is deleted, so its number
        # is never reused by the next one created that month. Visible/
        # editable under Settings > Technical > Sequences.
        yymm = fields.Date.context_today(self).strftime('%y%m')
        prefix = f'JE-B-{yymm}-'
        code = f'bulletin.bulletin.{yymm}'
        IrSequence = self.env['ir.sequence'].sudo()
        # Serialize "does this month's sequence exist yet" against other
        # transactions doing the same check at the same instant - without
        # this, two concurrent first-of-the-month creates could both see
        # none exists and each create their own ir.sequence row sharing
        # the same code, causing duplicate/inconsistent numbering.
        self.env.cr.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (code,))
        number = IrSequence.next_by_code(code)
        if not number:
            # First Bulletin of this month: seed the counter past any
            # already-existing numbers (e.g. from before this sequence
            # existed) so it can't collide with them.
            last = self.search([('name', 'like', prefix + '%')], order='name desc', limit=1)
            number_next = 1
            if last:
                tail = last.name[len(prefix):]
                if tail.isdigit():
                    number_next = int(tail) + 1
            IrSequence.create({
                'name': f'Bulletin Document Number - {yymm}',
                'code': code,
                'implementation': 'no_gap',
                'prefix': prefix,
                'padding': 2,
                'number_increment': 1,
                'number_next': number_next,
            })
            number = IrSequence.next_by_code(code)
        return number

    def action_print_pdf(self):
        self.ensure_one()
        self._check_required_sections()
        return self.env.ref('bulletin.action_report_bulletin').report_action(self)

    def _check_required_sections(self):
        """Block printing (not saving, so drafts can still be saved
        incomplete) while a Section the Template marked Required is empty."""
        self.ensure_one()
        required_section_ids = self.template_id.section_ids.filtered('required').mapped('section_id')
        missing = []
        for line in self.section_ids.filtered(lambda l: l.section_id in required_section_ids):
            if line.content_type == 'html' and not (line.content and html2plaintext(line.content).strip()):
                missing.append(line.name)
            elif line.content_type == 'authorisation' and not line.approver_id:
                missing.append(line.name)
        if missing:
            raise UserError(_('These required sections are still empty: %s') % ', '.join(missing))

    def _get_subject_text(self):
        """Plain-text content of the Section named "Subject", for the report
        footer - empty if this Bulletin's Template has no such Section."""
        self.ensure_one()
        subject_line = self.section_ids.filtered(lambda s: s.name == 'Subject')[:1]
        return html2plaintext(subject_line.content or '') if subject_line else ''


class BulletinBulletinSection(models.Model):
    _name = 'bulletin.bulletin.section'
    _description = 'Bulletin Content Section'
    _inherit = ['jacon.html.attachment.mixin']
    _order = 'sequence, id'

    bulletin_id = fields.Many2one('bulletin.bulletin', required=True, ondelete='cascade')
    section_id = fields.Many2one('bulletin.section', string='Section', required=True)
    template_section_id = fields.Many2one(
        'bulletin.template.section', string='Template Section', ondelete='set null',
        help="The Template's section slot this line was created from - keeps the "
             "sequence live-linked, so reordering sections in the Template also "
             "reorders them here, even on Bulletins created before the reorder.")
    name = fields.Char(related='section_id.name', string='Header', readonly=True)
    content_type = fields.Selection(related='section_id.content_type', readonly=True)
    sequence = fields.Integer(compute='_compute_sequence', store=True, readonly=True)
    content = fields.Html(sanitize_attributes=False)
    approver_id = fields.Many2one('hr.employee', string='Approver')
    approver_name = fields.Char(related='approver_id.name', readonly=True)
    approver_job_title = fields.Char(related='approver_id.job_title', readonly=True)

    @api.depends('template_section_id.sequence')
    def _compute_sequence(self):
        # A plain related field would reset to 0 the moment
        # template_section_id gets nullified (e.g. that slot is later
        # deleted from the Template), jumbling this line's position both
        # on the form and in the PDF. Falling through without assigning
        # keeps whatever sequence this line last had.
        for rec in self:
            if rec.template_section_id:
                rec.sequence = rec.template_section_id.sequence

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._adopt_embedded_image_attachments(('content',))
        return records

    def write(self, vals):
        result = super().write(vals)
        if 'content' in vals:
            self._adopt_embedded_image_attachments(('content',))
        return result
