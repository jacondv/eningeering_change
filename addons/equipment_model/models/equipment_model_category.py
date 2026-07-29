from odoo import fields, models


class EquipmentModelCategory(models.Model):
    """A product line grouping several Equipment Models (e.g. all the
    variants sold under one commercial line), independent of the
    parent/child design-inheritance hierarchy on `equipment.model` itself.
    """
    _name = 'equipment.model.category'
    _description = 'Equipment Model Category'
    _order = 'name'

    name = fields.Char(required=True, index=True)
    description = fields.Text()
    model_ids = fields.One2many('equipment.model', 'category_id', string='Models')
    model_count = fields.Integer(compute='_compute_model_count')
    active = fields.Boolean(default=True)

    def _compute_model_count(self):
        for rec in self:
            rec.model_count = len(rec.model_ids)
