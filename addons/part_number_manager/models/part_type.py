from odoo import fields, models


class PartType(models.Model):
    """One BOM-built part category (e.g. "Bearing Assembly"). Declares which
    `part_attribute` records apply to parts of this type - the EAV schema
    itself lives on part_attribute/part_attribute_value (see techspec 2.3).
    """
    _name = 'part_number_manager.part_type'
    _description = 'Part Type'
    _order = 'name'

    name = fields.Char(required=True)
    attribute_ids = fields.Many2many(
        'part_number_manager.part_attribute',
        'part_number_manager_part_type_attribute_rel',
        'part_type_id', 'attribute_id',
        string='Attributes')
