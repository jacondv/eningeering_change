from odoo import api, fields, models


class QcChecksheetInventorImportWizard(models.TransientModel):
    """"Import from Inventor BOM" button on the check sheet form (techspec
    §6): pick any inventor.bom of type panel_sticker (defaults to one
    matching this checksheet's Machine Model if there is one, but the full
    list is always searchable), tick/edit which lines to bring in, and
    copy them into panel_line_ids."""
    _name = 'qc.checksheet.inventor.import.wizard'
    _description = 'Import Panel Lines from Inventor BOM'

    checksheet_id = fields.Many2one('qc.checksheet', required=True)
    bom_id = fields.Many2one(
        'inventor.bom', string='Inventor BOM', required=True,
        domain=[('bom_type', '=', 'panel_sticker')])
    line_ids = fields.One2many(
        'qc.checksheet.inventor.import.wizard.line', 'wizard_id', string='Lines')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if 'bom_id' in fields_list and res.get('checksheet_id'):
            checksheet = self.env['qc.checksheet'].browse(res['checksheet_id'])
            bom = self.env['inventor.bom'].search([
                ('bom_type', '=', 'panel_sticker'),
                ('model', '=', checksheet.machine_model),
            ], limit=1)
            if bom:
                res['bom_id'] = bom.id
        return res

    @api.onchange('bom_id')
    def _onchange_bom_id(self):
        self.line_ids = [(5, 0, 0)] + [
            (0, 0, {
                'selected': True,
                'item': line.item,
                'part_number': line.part_number,
                'description': line.description,
                'qty': line.qty,
                'image': line.image,
            })
            for line in self.env['qc.checksheet.inventor.bom.line'].search([('bom_id', '=', self.bom_id.id)])
        ]

    def action_import(self):
        self.ensure_one()
        for line in self.line_ids.filtered('selected'):
            self.env['qc.checksheet.panel.line'].create({
                'checksheet_id': self.checksheet_id.id,
                'item_number': line.item,
                'part_number': line.part_number,
                'description': line.description,
                'image': line.image,
                'qty': line.qty,
            })
        return {'type': 'ir.actions.act_window_close'}


class QcChecksheetInventorImportWizardLine(models.TransientModel):
    """One editable row per line pulled from the selected BOM, shown in the
    Import wizard so the user can tick which ones to bring in and correct
    anything before it's copied - these are independent working copies, not
    linked back to the source qc.checksheet.inventor.bom.line, so editing
    here never mutates the BOM Inventor sent."""
    _name = 'qc.checksheet.inventor.import.wizard.line'
    _description = 'Import Panel Line Selection Row'

    wizard_id = fields.Many2one(
        'qc.checksheet.inventor.import.wizard', required=True, ondelete='cascade')
    selected = fields.Boolean(default=True)
    item = fields.Integer()
    part_number = fields.Char()
    description = fields.Char()
    qty = fields.Integer()
    image = fields.Image(max_width=1920, max_height=1920)
