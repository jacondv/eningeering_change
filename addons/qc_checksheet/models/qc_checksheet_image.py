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
    image_line_ids = fields.One2many('qc.checksheet.image.line', 'image_group_id', string='Images')


class QcChecksheetImageLine(models.Model):
    _name = 'qc.checksheet.image.line'
    _description = 'QC Check Sheet Image Line'
    _order = 'sequence, id'

    image_group_id = fields.Many2one('qc.checksheet.image.group', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    image = fields.Image(max_width=1920, max_height=1920)
    description = fields.Char()
    size_percent = fields.Integer(
        string='Height (% of page)', default=30,
        help="Printed image height as a percentage of the page's usable content height "
             "(~600pt on A4, after header/footer margins). 100% = about a full page tall.")
    width_percent = fields.Integer(
        string='Width (% of row)', default=100,
        help="Width of this image's own column as a percentage of the printed row - only "
             "matters when the group shows a Description column, since it controls how far "
             "the description text sits from the image. The image itself always keeps its "
             "aspect ratio (Height is the primary size driver) and never stretches to fill "
             "the column - a wider column just pushes the Description further right.")
