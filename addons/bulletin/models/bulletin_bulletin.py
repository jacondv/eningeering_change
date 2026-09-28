from odoo import api, fields, models
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

    @api.onchange('template_id')
    def _onchange_template_id(self):
        for rec in self:
            lines = [(0, 0, {
                'section_id': tsec.section_id.id,
                'sequence': tsec.sequence,
                'approver_id': tsec.default_approver_id.id,
            }) for tsec in rec.template_id.section_ids.sorted('sequence')]
            rec.section_ids = [(5, 0, 0)] + lines

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals['name'] == 'New':
                vals['name'] = self._generate_document_number()
        return super().create(vals_list)

    def _generate_document_number(self):
        yymm = fields.Date.context_today(self).strftime('%y%m')
        prefix = f'JE-B-{yymm}-'
        last = self.search([('name', 'like', prefix + '%')], order='name desc', limit=1)
        seq = 1
        if last:
            tail = last.name[len(prefix):]
            if tail.isdigit():
                seq = int(tail) + 1
        return f'{prefix}{seq:02d}'

    def action_print_pdf(self):
        self.ensure_one()
        return self.env.ref('bulletin.action_report_bulletin').report_action(self)

    def _get_subject_text(self):
        """Plain-text content of the Section named "Subject", for the report
        footer - empty if this Bulletin's Template has no such Section."""
        self.ensure_one()
        subject_line = self.section_ids.filtered(lambda s: s.name == 'Subject')[:1]
        return html2plaintext(subject_line.content or '') if subject_line else ''


class BulletinBulletinSection(models.Model):
    _name = 'bulletin.bulletin.section'
    _description = 'Bulletin Content Section'
    _order = 'sequence, id'

    bulletin_id = fields.Many2one('bulletin.bulletin', required=True, ondelete='cascade')
    section_id = fields.Many2one('bulletin.section', string='Section', required=True)
    name = fields.Char(related='section_id.name', string='Header', readonly=True)
    help_text = fields.Text(related='section_id.help_text', readonly=True)
    content_type = fields.Selection(related='section_id.content_type', readonly=True)
    sequence = fields.Integer(default=10)
    content = fields.Html(sanitize_attributes=False)
    approver_id = fields.Many2one('hr.employee', string='Approver')
    approver_name = fields.Char(related='approver_id.name', readonly=True)
    approver_job_title = fields.Char(related='approver_id.job_title', readonly=True)
    company_name = fields.Char(related='bulletin_id.company_id.name', readonly=True)
