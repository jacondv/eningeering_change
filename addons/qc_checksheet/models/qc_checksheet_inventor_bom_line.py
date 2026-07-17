from odoo import fields, models


class QcChecksheetInventorBomLine(models.Model):
    """Line of a 'panel_sticker' inventor.bom, as registered in
    inventor.bom.type (see data/inventor_bom_type_data.xml). Usually
    populated wholesale by the inventor_connector REST endpoint, but can
    also be added/edited by hand from the BOM's own form (see the
    panel_sticker_line_ids extension below). The Import wizard copies
    selected lines into qc.checksheet.panel.line (techspec §6)."""
    _name = 'qc.checksheet.inventor.bom.line'
    _description = 'QC Check Sheet Inventor BOM Line'
    _order = 'item, id'

    bom_id = fields.Many2one('inventor.bom', required=True, ondelete='cascade')
    item = fields.Integer(help="Display sequence number as sent by Inventor - not auto-incrementing.")
    description = fields.Char()
    qty = fields.Integer(default=1)
    part_number = fields.Char()
    image = fields.Image(max_width=1920, max_height=1920)


class InventorBom(models.Model):
    """Extend the generic inventor.bom (from inventor_connector) with a
    direct One2many to this module's own line model, so a 'panel_sticker'
    BOM's content is visible/editable straight from its own form - the
    connector itself stays agnostic and has no such field."""
    _inherit = 'inventor.bom'

    panel_sticker_line_ids = fields.One2many(
        'qc.checksheet.inventor.bom.line', 'bom_id', string='Panel & Sticker Lines')
