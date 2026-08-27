from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class MaterialGroup(models.Model):
    """Defines the 4-digit prefix of a part number. Each part number is
    `material_group.code` (4 digits) + a 4-digit gap-filling sequence
    suffix computed on part_number (see techspec 2.4).
    """
    _name = 'part_number_manager.material_group'
    _description = 'Part Number Material Group'
    _order = 'code'

    code = fields.Char(required=True, index=True)
    description = fields.Char(required=True)
    category_id = fields.Many2one(
        'part_number_manager.material_category', string='Main Category', required=True, index=True,
        help="Used to narrow the Material Group picker to a two-step selection - "
             "not otherwise validated against `code`.")

    _code_unique = models.Constraint('unique(code)', 'This Material Group code already exists.')

    @api.constrains('code')
    def _check_code_format(self):
        for rec in self:
            if not (rec.code and rec.code.isdigit() and len(rec.code) == 4):
                raise ValidationError(_('Material Group code must be exactly 4 digits.'))

    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f'{rec.code} - {rec.description}'

    def name_search(self, name='', domain=None, operator='ilike', limit=100):
        # Same fix as material_category.name_search - see that method for
        # why this is needed (display_name is computed, not a real column,
        # so without _rec_name the base implementation can't filter by it).
        domain = list(domain or [])
        if name:
            records = self.search(domain)
            if operator == '=':
                records = records.filtered(lambda r: r.display_name == name)
            else:
                norm = name.lower()
                records = records.filtered(lambda r: norm in (r.display_name or '').lower())
            records = records[:limit]
        else:
            records = self.search(domain, limit=limit)
        return [(r.id, r.display_name) for r in records]
