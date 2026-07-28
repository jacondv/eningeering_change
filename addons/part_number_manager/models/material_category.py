from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class MaterialCategory(models.Model):
    """The 2-digit "Main Category" a Material Group belongs to (e.g. "10 -
    Axle & spare parts" groups "1000 - Comer axle & spare", "1001 - Dana
    axle & spare", ...). Exists purely so picking a Material Group is a fast
    two-step selection (category, then group) instead of scrolling/searching
    the flat list of every 4-digit code at once.
    """
    _name = 'part_number_manager.material_category'
    _description = 'Material Main Category'
    _order = 'code'

    code = fields.Char(required=True, index=True)
    description = fields.Char(required=True)
    group_ids = fields.One2many(
        'part_number_manager.material_group', 'category_id', string='Material Groups')

    _code_unique = models.Constraint('unique(code)', 'This Main Category code already exists.')

    @api.constrains('code')
    def _check_code_format(self):
        for rec in self:
            if not (rec.code and rec.code.isdigit() and len(rec.code) == 2):
                raise ValidationError(_('Main Category code must be exactly 2 digits.'))

    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f'{rec.code} - {rec.description}'
