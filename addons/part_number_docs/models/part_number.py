from odoo import _, api, fields, models, tools
from odoo.exceptions import AccessError


class PartNumber(models.Model):
    _inherit = 'part_number_manager.part_number'

    pnd_document_ids = fields.Many2many(
        'pnd.document', 'pnd_document_part_rel', 'part_number_id', 'document_id', string="Documents",
        groups='part_number_docs.group_pnd_view',
    )
    pnd_document_count = fields.Integer(
        string="Documents", compute='_compute_pnd_document_count', groups='part_number_docs.group_pnd_view',
    )
    pnd_can_edit = fields.Boolean(compute='_compute_pnd_can_edit')

    def _compute_pnd_document_count(self):
        counts = {}
        if self.ids:  # counted in the database: the documents themselves are not read
            self.env.cr.execute(
                "SELECT part_number_id, COUNT(*) FROM pnd_document_part_rel WHERE part_number_id IN %s GROUP BY 1",
                (tuple(self.ids),),
            )
            counts = dict(self.env.cr.fetchall())
        for part in self:
            part.pnd_document_count = counts.get(part.id, 0)

    @api.depends_context('uid')
    def _compute_pnd_can_edit(self):
        can_edit = self.env.user.has_group('part_number_docs.group_pnd_edit')
        for part in self:
            part.pnd_can_edit = can_edit

    def init(self):
        super().init()
        # The searches of the Part Documents page look inside these fields ('%word%'): a trigram index
        # keeps that fast when there are many part numbers.
        if self.env.registry.has_trigram:
            for column in ('part_number', 'short_description', 'long_description', 'display_description',
                           'legacy_codes_display', 'vendor_ref'):
                tools.create_index(
                    self.env.cr, 'pnd_trgm_%s' % column, self._table, ['%s gin_trgm_ops' % column], method='gin',
                )

    def write(self, vals):
        # Linking documents is for those who may edit documents, not for everyone who may edit a part number.
        if 'pnd_document_ids' in vals and not self.env.su and not self.env.user.has_group('part_number_docs.group_pnd_edit'):
            raise AccessError(_("You are not allowed to add or remove documents."))
        return super().write(vals)
