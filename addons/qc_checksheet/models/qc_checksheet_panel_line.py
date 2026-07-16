from odoo import fields, models


class QcChecksheetPanelLine(models.Model):
    """Panel & Sticker line. Every field is entered by hand - no lookup
    against product.product."""
    _name = 'qc.checksheet.panel.line'
    _description = 'QC Check Sheet Panel Line'
    _order = 'sequence, id'

    checksheet_id = fields.Many2one('qc.checksheet', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    part_number = fields.Char(string='Part Number')
    description = fields.Char()
    image = fields.Image(max_width=1920, max_height=1920)
    qty = fields.Float(string='Qty', default=1.0)
    note = fields.Char()
