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
    """One fixed choice of a Selection attribute (e.g. Hose Type "4G1").
    `no`/`description` hold reference data that belongs to the choice
    itself, not to whichever Part later picks it - e.g. Hose Type's
    description ('1/4" x 1SN') is fixed per Type, never retyped per Hose
    (see techspec: Hose & Fitting). `no` is free text, not a sequence -
    it's the source table's own reference letter/number (e.g. "A"), kept
    only for traceability back to that table on Excel export.
    """
    _name = 'part_number_manager.part_attribute_option'
    _description = 'Part Attribute Option'
    _order = 'attribute_id, id'

    attribute_id = fields.Many2one(
        'part_number_manager.part_attribute', required=True, ondelete='cascade')
    no = fields.Char(string='No.')
    name = fields.Char(required=True)
    description = fields.Char()


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
    option_description = fields.Char(
        related='value_option_id.description', string='Description',
        help="Read-only: the fixed description of the selected option (e.g. Hose Type's "
             "own '1/4\" x 1SN') - never entered here, only ever edited on the option itself "
             "under Configuration > Part Attributes.")
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
