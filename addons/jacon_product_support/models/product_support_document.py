from odoo import api, fields, models


class ProductSupportDocument(models.Model):
    """Related drawing/document of a Support Request - same shape as
    engineering.change.document, which can't be reused (it requires an EC)."""
    _name = 'product.support.document'
    _description = 'Product Support Related Drawing/Document'

    request_id = fields.Many2one('product.support.request', required=True, ondelete='cascade')
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
