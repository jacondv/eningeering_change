from odoo import fields, models


class JaconOfficeCategory(models.Model):
    _name = 'jacon.office.category'
    _description = 'Office Document Category'
    _order = 'sequence, name'

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    _unique_name = models.UniqueIndex('(lower(name))', "A category with this name already exists.")
