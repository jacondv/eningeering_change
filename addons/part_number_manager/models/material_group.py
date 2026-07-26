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

    code = fields.Char(required=True, size=4, index=True)
    description = fields.Char(required=True)

    _code_unique = models.Constraint('unique(code)', 'This Material Group code already exists.')

    @api.constrains('code')
    def _check_code_format(self):
        for rec in self:
            if not (rec.code and rec.code.isdigit() and len(rec.code) == 4):
                raise ValidationError(_('Material Group code must be exactly 4 digits.'))

    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f'{rec.code} - {rec.description}'
