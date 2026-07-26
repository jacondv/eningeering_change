from odoo import fields, models


class PartNumberMapping(models.Model):
    """N-N mapping between a new and a legacy part number. Old/new is a
    role of the relationship, not a fixed attribute of a record: in a
    multi-step conversion chain (A -> B -> C), B is simultaneously "new"
    (relative to A) and "legacy" (relative to C) - see techspec 2.2.
    """
    _name = 'part_number_manager.part_number_mapping'
    _description = 'Part Number Mapping (Legacy -> New)'

    new_part_id = fields.Many2one(
        'part_number_manager.part_number', required=True, ondelete='cascade')
    legacy_part_id = fields.Many2one(
        'part_number_manager.part_number', required=True, ondelete='cascade')

    _new_legacy_unique = models.Constraint(
        'unique(new_part_id, legacy_part_id)', 'This mapping already exists.')
