from odoo import fields, models


class BulletinSection(models.Model):
    """A reusable section header, insertable into any number of Templates
    (e.g. "Subject", "Issue Description", "Authorisation")."""
    _name = 'bulletin.section'
    _description = 'Bulletin Section'
    _order = 'name'

    name = fields.Char(required=True)
    help_text = fields.Text(
        string='Help Text',
        help="Shown to the author as guidance when filling this section on a Bulletin.")
    content_type = fields.Selection([
        ('html', 'Free Text'),
        ('authorisation', 'Approval & Signature'),
    ], string='Content Type', default='html', required=True,
        help="Free Text: an open HTML editor.\n"
             "Approval & Signature: picks an Employee and shows their signature, name and job title.")
    active = fields.Boolean(default=True)

    _name_uniq = models.Constraint('unique(name)', 'A section with this name already exists.')
