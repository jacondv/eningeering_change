from odoo import fields, models


class EquipmentModelCategory(models.Model):
    """A product line (Model Group) grouping several Product Families, each
    of which in turn groups several Equipment Models - independent of the
    parent/child design-inheritance hierarchy on `equipment.model` itself.
    """
    _name = 'equipment.model.category'
    _description = 'Equipment Model Category'
    _order = 'name'

    name = fields.Char(required=True, index=True)
    description = fields.Text()
    family_ids = fields.One2many('equipment.model.family', 'category_id', string='Product Families')
    family_count = fields.Integer(compute='_compute_family_count')
    model_count = fields.Integer(compute='_compute_model_count')
    active = fields.Boolean(default=True)

    def _compute_family_count(self):
        for rec in self:
            rec.family_count = len(rec.family_ids)

    def _compute_model_count(self):
        for rec in self:
            rec.model_count = sum(len(family.model_ids) for family in rec.family_ids)
