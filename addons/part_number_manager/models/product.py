from odoo import _, fields, models
from odoo.exceptions import UserError


class ProductProduct(models.Model):
    _inherit = 'product.product'

    pnm_part_ids = fields.One2many('part_number_manager.part_number', 'product_id', string='Part Number')

    # Internal Reference = Part Number, which is unique - Odoo itself only
    # warns on duplicates while typing.
    _pnm_default_code_unique = models.UniqueIndex('(default_code) WHERE default_code IS NOT NULL')

    def write(self, vals):
        if 'default_code' in vals and not self.env.context.get('pnm_sync'):
            linked = self.sudo().filtered(lambda p: p.pnm_part_ids and p.default_code != vals['default_code'])
            if linked:
                raise UserError(_(
                    'Internal Reference of %s is managed by its Part Number - change it there instead.',
                    ', '.join(linked.mapped('display_name'))))
        return super().write(vals)


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    pnm_part_id = fields.Many2one(
        'part_number_manager.part_number', string='Part Number', compute='_compute_pnm_part_id')

    def _compute_pnm_part_id(self):
        for template in self:
            template.pnm_part_id = template.sudo().with_context(active_test=False).product_variant_ids.pnm_part_ids[:1]

    def action_open_pnm_part(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'part_number_manager.part_number',
            'res_id': self.pnm_part_id.id,
            'view_mode': 'form',
        }
