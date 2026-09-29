from odoo import fields, models


class BulletinTemplate(models.Model):
    """A named bulletin type (e.g. "SAFETY BULLETIN") - defines which
    sections a Bulletin created from it starts with, and in what order."""
    _name = 'bulletin.template'
    _description = 'Bulletin Template'
    _order = 'name'

    name = fields.Char(required=True)
    section_ids = fields.One2many('bulletin.template.section', 'template_id', string='Sections', copy=True)
    active = fields.Boolean(default=True)


class BulletinTemplateSection(models.Model):
    """One section slot within a Template, in sequence order."""
    _name = 'bulletin.template.section'
    _description = 'Bulletin Template Section'
    _order = 'sequence, id'

    template_id = fields.Many2one('bulletin.template', required=True, ondelete='cascade')
    section_id = fields.Many2one('bulletin.section', string='Section', required=True)
    content_type = fields.Selection(related='section_id.content_type', readonly=True)
    sequence = fields.Integer(default=10)
    required = fields.Boolean(string='Required')
    default_approver_id = fields.Many2one(
        'hr.employee', string='Default Approver',
        help="Pre-filled as the Approver on any Bulletin created from this Template "
             "(only used when the Section is an Approval & Signature type).")
