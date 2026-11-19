from odoo import _, fields, models
from odoo.exceptions import UserError


class PndDocumentMergeWizard(models.TransientModel):
    """Several documents that turned out to be the same one: the part numbers of all of them go to the
    one that is kept, and the others are removed."""
    _name = 'pnd.document.merge.wizard'
    _description = 'Merge Part Documents'

    document_ids = fields.Many2many('pnd.document', string="Documents", required=True)
    keep_id = fields.Many2one(
        'pnd.document', string="Keep", required=True, domain="[('id', 'in', document_ids)]",
        help="The document that stays; the others are removed after their part numbers are moved to it.")

    def action_merge(self):
        self.ensure_one()
        self.env['pnd.document']._check_group('part_number_docs.group_pnd_edit')
        self.document_ids.check_access('write')  # merging is for documents the user may change
        keep = self.keep_id.sudo()
        others = self.document_ids.sudo() - keep
        if keep not in self.document_ids or not others:
            raise UserError(_("Choose the document to keep among the selected ones."))
        names = ', '.join(others.mapped('name'))
        keep.part_number_ids |= others.part_number_ids
        if not keep.vendor_id and others.vendor_id:
            keep.vendor_id = others.vendor_id[:1]
        keep.message_post(body=_("%(user)s merged into this document: %(names)s.", user=self.env.user.name, names=names))
        others.unlink()  # the files go with them (the Edit level may merge, only Manage may delete otherwise)
        # Back to where the user was (the search page, or the list): not to the document's form.
        return {'type': 'ir.actions.act_window_close'}
