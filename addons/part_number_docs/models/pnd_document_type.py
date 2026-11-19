from odoo import fields, models


class PndDocumentType(models.Model):
    """What a document is: Datasheet, Manual, Drawing... Managers keep the list."""
    _name = 'pnd.document.type'
    _description = 'Part Document Type'
    _order = 'sequence, name'

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    _unique_name = models.UniqueIndex('(lower(name)) WHERE active', "A document type with this name already exists.")
