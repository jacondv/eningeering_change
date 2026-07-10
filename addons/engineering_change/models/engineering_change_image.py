from odoo import fields, models


class EngineeringChangeImage(models.Model):
    _name = 'engineering.change.image'
    _description = 'Engineering Change Image'

    change_id = fields.Many2one('engineering.change', required=True, ondelete='cascade')
    image = fields.Image(required=True, max_width=1920, max_height=1920)
    caption = fields.Char()
