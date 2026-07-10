from odoo import api, fields, models


class EngineeringChangeDocument(models.Model):
    _name = 'engineering.change.document'
    _description = 'Engineering Change Related Drawing/Document'

    change_id = fields.Many2one('engineering.change', required=True, ondelete='cascade')
    name = fields.Char(required=True)
    doc_type = fields.Selection([
        ('link', 'Link'),
        ('file', 'File'),
    ], required=True, default='link')
    link = fields.Char(string='Link / Path')
    attachment = fields.Binary(string='Attachment')
    attachment_filename = fields.Char(string='File Name')

    @api.onchange('attachment_filename')
    def _onchange_attachment_filename(self):
        if self.attachment_filename and not self.name:
            self.name = self.attachment_filename
