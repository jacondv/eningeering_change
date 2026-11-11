from odoo import fields, models


class QcChecksheetCopyWizard(models.TransientModel):
    """"Copy Content From..." button on a Draft first Revision: pick another Model's
    Released check sheet of the same Type and bring its content over."""
    _name = 'qc.checksheet.copy.wizard'
    _description = 'Copy QC Check Sheet Content'

    checksheet_id = fields.Many2one('qc.checksheet', required=True)
    source_checksheet_id = fields.Many2one(
        'qc.checksheet', string='Copy Content From', required=True,
        domain="[('type_id', '=', type_id), ('id', '!=', checksheet_id), ('state', '=', 'released')]")
    type_id = fields.Many2one(related='checksheet_id.type_id')

    def action_copy(self):
        self.ensure_one()
        self.checksheet_id._copy_content_from(self.source_checksheet_id)
        return {'type': 'ir.actions.act_window_close'}
