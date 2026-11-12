from odoo import api, fields, models


class JaconOfficeMixin(models.AbstractModel):
    """Lets a model own Office Documents.

    A model inherits this and shows `office_document_ids` (and the
    `action_new_office_document` button) wherever it wants, usually in a tab of
    its form; that view part lives in a small glue addon per model.
    """
    _name = 'jacon.office.mixin'
    _description = 'Owner of Office Documents'

    office_document_ids = fields.One2many('jacon.office.document', 'res_id', string="Documents")
    office_document_count = fields.Integer(string="Document Count", compute='_compute_office_document_count')

    @api.depends('office_document_ids')
    def _compute_office_document_count(self):
        counts = dict(self.env['jacon.office.document']._read_group(
            [('res_model', '=', self._name), ('res_id', 'in', self._origin.ids)],
            ['res_id'], ['__count'],
        ))
        for record in self:
            record.office_document_count = counts.get(record._origin.id, 0)

    def _office_is_locked(self):
        """Whether this record's documents can no longer be added to or edited.

        Override it, e.g. to lock the documents of a Closed Project. Reading
        and downloading stay possible.
        """
        self.ensure_one()
        return False

    def action_new_office_document(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._("New Document"),
            'res_model': 'jacon.office.document.create.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_res_model': self._name, 'default_res_id': self.id},
        }

    def unlink(self):
        documents = self.env['jacon.office.document'].sudo().with_context(active_test=False).search([
            ('res_model', '=', self._name), ('res_id', 'in', self.ids),
        ])
        res = super().unlink()
        documents.unlink()
        return res
