from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class PartAttribute(models.Model):
    """One EAV attribute definition (e.g. "Length", "Material"). Adding a
    new attribute is just a new record here - no code/DB migration needed
    (see techspec 2.3).
    """
    _name = 'part_number_manager.part_attribute'
    _description = 'Part Attribute'
    _order = 'name'

    name = fields.Char(required=True)
    value_type = fields.Selection([
        ('float', 'Number'),
        ('char', 'Text'),
        ('selection', 'Selection'),
    ], default='char', required=True)
    uom = fields.Char(string='Unit of Measure')
    option_ids = fields.One2many(
        'part_number_manager.part_attribute_option', 'attribute_id', string='Options')


class PartAttributeOption(models.Model):
    _name = 'part_number_manager.part_attribute_option'
    _description = 'Part Attribute Option'
    _order = 'attribute_id, name'

    attribute_id = fields.Many2one(
        'part_number_manager.part_attribute', required=True, ondelete='cascade')
    name = fields.Char(required=True)


class PartAttributeValue(models.Model):
    """Value of one attribute for one part number (EAV row). Only the
    column matching `attribute_id.value_type` is meaningful (see techspec
    3.7); the others stay empty.
    """
    _name = 'part_number_manager.part_attribute_value'
    _description = 'Part Attribute Value'

    part_id = fields.Many2one(
        'part_number_manager.part_number', required=True, ondelete='cascade')
    attribute_id = fields.Many2one(
        'part_number_manager.part_attribute', required=True)
    value_type = fields.Selection(related='attribute_id.value_type', string='Value Type')
    value_float = fields.Float()
    value_char = fields.Char()
    value_option_id = fields.Many2one('part_number_manager.part_attribute_option')
    display_value = fields.Char(compute='_compute_display_value', store=True)

    @api.depends('attribute_id.value_type', 'attribute_id.uom', 'value_float', 'value_char', 'value_option_id')
    def _compute_display_value(self):
        for rec in self:
            value_type = rec.attribute_id.value_type
            if value_type == 'float':
                text = str(rec.value_float)
                if rec.attribute_id.uom:
                    text = f'{text} {rec.attribute_id.uom}'
                rec.display_value = text
            elif value_type == 'selection':
                rec.display_value = rec.value_option_id.name or ''
            else:
                rec.display_value = rec.value_char or ''

    @api.constrains('value_option_id', 'attribute_id')
    def _check_option_belongs_to_attribute(self):
        for rec in self:
            if rec.value_option_id and rec.value_option_id.attribute_id != rec.attribute_id:
                raise ValidationError(_('The selected option does not belong to this attribute.'))
