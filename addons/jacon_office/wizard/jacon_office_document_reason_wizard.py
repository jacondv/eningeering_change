from odoo import _, fields, models
from odoo.exceptions import UserError


class JaconOfficeDocumentReasonWizard(models.TransientModel):
    """Asks why before a document is rejected or a new Rev of it is opened."""
    _name = 'jacon.office.document.reason.wizard'
    _description = 'Reason for a Document Change'

    document_id = fields.Many2one('jacon.office.document', required=True, ondelete='cascade')
    version_id = fields.Many2one('jacon.office.document.version', string="Start From", ondelete='cascade')
    mode = fields.Selection([('reject', "Reject"), ('new_rev', "New Rev")], required=True)
    reason = fields.Text(required=True)

    def action_confirm(self):
        self.ensure_one()
        if not (self.reason or '').strip():
            raise UserError(_("Write the reason first."))
        if self.mode == 'reject':
            self.document_id.action_reject(self.reason)
        else:
            self.document_id.action_new_revision(self.reason, self.version_id)
        return {'type': 'ir.actions.act_window_close'}
