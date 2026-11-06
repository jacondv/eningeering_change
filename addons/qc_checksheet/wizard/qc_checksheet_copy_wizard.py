from odoo import fields, models


class QcChecksheetCopyWizard(models.TransientModel):
    """"Copy Content From..." button on a Draft Rev 0: pick another Job's
    Released check sheet of the same layout and bring its content over."""
    _name = 'qc.checksheet.copy.wizard'
    _description = 'Copy QC Check Sheet Content'

    checksheet_id = fields.Many2one('qc.checksheet', required=True)
    source_checksheet_id = fields.Many2one(
        'qc.checksheet', string='Copy Content From', required=True,
        domain="[('checksheet_type', '=', checksheet_type), ('id', '!=', checksheet_id), ('state', '=', 'released')]")
    checksheet_type = fields.Selection(related='checksheet_id.checksheet_type')

    def action_copy(self):
        self.ensure_one()
        self.checksheet_id._copy_content_from(self.source_checksheet_id)
        return {'type': 'ir.actions.act_window_close'}
