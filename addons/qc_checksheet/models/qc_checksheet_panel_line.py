from odoo import api, fields, models


class QcChecksheetPanelLine(models.Model):
    """Panel & Sticker line. `part_number` is looked up against
    product.product by default_code; description/image auto-fill from the
    product but stay manually editable/overridable afterwards (techspec
    §2.2, §3.4)."""
    _name = 'qc.checksheet.panel.line'
    _description = 'QC Check Sheet Panel Line'
    _order = 'sequence, id'

    checksheet_id = fields.Many2one('qc.checksheet', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    part_number = fields.Many2one('product.product', string='Part Number')
    description = fields.Char()
    image = fields.Image(max_width=1920, max_height=1920)
    qty = fields.Float(string='Qty', default=1.0)
    note = fields.Char()
    product_found = fields.Boolean(compute='_compute_product_found', store=True)

    @api.depends('part_number')
    def _compute_product_found(self):
        for rec in self:
            rec.product_found = bool(rec.part_number)

    @api.onchange('part_number')
    def _onchange_part_number(self):
        if self.part_number:
            self.description = self.part_number.name
            self.image = self.part_number.image_1920

    def action_update_from_product(self):
        """"Update Part Number image" button, row-level (techspec §3.4)."""
        for rec in self.filtered('part_number'):
            rec.description = rec.part_number.name
            rec.image = rec.part_number.image_1920
