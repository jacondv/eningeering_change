from odoo import models


class IrAttachment(models.Model):
    _inherit = 'ir.attachment'

    def write(self, vals):
        """Writing the content of a document's file (ONLYOFFICE saving an edit, a Rev started from an
        older one) notes who edited and makes the PDF out of date, see
        `jacon.office.document._content_written`."""
        if not ({'raw', 'datas'} & vals.keys()) or not self._may_be_a_document_file():
            return super().write(vals)
        documents = self.env['jacon.office.document'].sudo().with_context(active_test=False).search([
            ('attachment_id', 'in', self.ids),
        ])
        if not documents:
            return super().write(vals)
        # (`_content_written` ignores a save of what the file already held.)
        before = {doc.id: doc.attachment_id.checksum for doc in documents}
        res = super().write(vals)
        documents._content_written(before)
        return res

    def _may_be_a_document_file(self):
        """A document's file is linked to the document: any other attachment can be left alone."""
        return any(model == 'jacon.office.document' for model in self.sudo().mapped('res_model'))
