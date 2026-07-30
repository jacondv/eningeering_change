from odoo import fields, models


class EquipmentModelFamily(models.Model):
    """A product family within a Model Category (e.g. all the variants of
    one commercial product line), grouping the individual Equipment Models
    that belong to it.
    """
    _name = 'equipment.model.family'
    _description = 'Equipment Model Family'
    _order = 'name'

    name = fields.Char(required=True, index=True)
    description = fields.Text()
    category_id = fields.Many2one(
        'equipment.model.category', string='Category', required=True, index=True)
    model_ids = fields.One2many('equipment.model', 'family_id', string='Models')
    model_count = fields.Integer(compute='_compute_model_count')
    active = fields.Boolean(default=True)

    def _compute_model_count(self):
        for rec in self:
            rec.model_count = len(rec.model_ids)
