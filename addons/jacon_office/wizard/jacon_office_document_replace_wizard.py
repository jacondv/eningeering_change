import base64

from odoo import _, fields, models
from odoo.exceptions import UserError


class JaconOfficeDocumentReplaceWizard(models.TransientModel):
    """Puts a file made elsewhere (a download that was changed in Office) in place of a Draft's file."""
    _name = 'jacon.office.document.replace.wizard'
    _description = 'Replace the File of a Document'

    document_id = fields.Many2one('jacon.office.document', required=True, ondelete='cascade')
    kind = fields.Selection(related='document_id.kind')
    upload = fields.Binary(string="New File", attachment=False)
    upload_filename = fields.Char()

    def action_confirm(self):
        self.ensure_one()
        if not self.upload:
            raise UserError(_("Choose the file first."))
        # A Binary field holds base64: the file's own bytes are what the document is given.
        self.document_id.action_replace_file(base64.b64decode(self.upload), self.upload_filename)
        return {'type': 'ir.actions.act_window_close'}
