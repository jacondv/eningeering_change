from odoo import fields, models


class ProductSupportFaultCategory(models.Model):
    _name = 'product.support.fault.category'
    _description = 'Product Support Fault Category'
    _order = 'sequence, name'

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    _name_uniq = models.Constraint('unique(name)', 'This Fault Category already exists.')
