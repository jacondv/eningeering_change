from odoo import fields, models


class QcChecksheetNewRevisionWizard(models.TransientModel):
    """"New Revision" button on the check sheet form: asks why the sheet is
    changing, then opens the next Draft Revision."""
    _name = 'qc.checksheet.new.revision.wizard'
    _description = 'Create QC Check Sheet Revision'

    checksheet_id = fields.Many2one('qc.checksheet', required=True)
    reason = fields.Char(string='Reason for Change', required=True)
    change_ids = fields.Many2many(
        'engineering.change', string='Engineering Changes',
        domain=[('state', 'not in', ['draft', 'canceled'])],
        help="The Engineering Changes behind this Revision, if any. Printed in the Revision History.")

    def action_create(self):
        self.ensure_one()
        return self.checksheet_id.action_create_revision(self.reason, self.change_ids.ids)
