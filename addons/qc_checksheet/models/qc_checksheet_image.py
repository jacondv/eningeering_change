from odoo import fields, models


class QcChecksheetImageGroup(models.Model):
    """Panel & Sticker "Location" image group (e.g. "Overview", "In the
    cabin") - printed as its own numbered sub-section (1.1, 1.2, ...) ahead
    of the Panel & Sticker Check List table."""
    _name = 'qc.checksheet.image.group'
    _description = 'QC Check Sheet Image Group'
    _order = 'sequence, id'

    checksheet_id = fields.Many2one('qc.checksheet', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    name = fields.Char(required=True)
    show_description = fields.Boolean(
        string='Show Description Column', default=True,
        help="Uncheck to print this group's images full-width, without a Description column.")
    image_line_ids = fields.One2many('qc.checksheet.image.line', 'image_group_id', string='Images')


class QcChecksheetImageLine(models.Model):
    _name = 'qc.checksheet.image.line'
    _description = 'QC Check Sheet Image Line'
    _order = 'sequence, id'

    image_group_id = fields.Many2one('qc.checksheet.image.group', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    image = fields.Image(max_width=1920, max_height=1920)
    description = fields.Char()
