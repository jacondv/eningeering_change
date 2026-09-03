from odoo import api, fields, models
from odoo.exceptions import ValidationError


class EquipmentCertificate(models.Model):
    """A free-depth reference tree for certificates/standards lookup
    (e.g. Certificates > Trailers > AU > S30 - Certificate #...).
    Any node may carry a rich-text `description`; leaf nodes are simply
    nodes with no `child_ids`.
    """
    _name = 'equipment.certificate'
    _description = 'Equipment Certificate Reference'
    _order = 'sequence, name'
    _parent_store = True
    _parent_name = 'parent_id'
    _rec_name = 'complete_name'

    name = fields.Char(required=True, index=True)
    sequence = fields.Integer(default=10)
    parent_id = fields.Many2one(
        'equipment.certificate', string='Parent', index=True, ondelete='cascade')
    parent_path = fields.Char(index=True)
    child_ids = fields.One2many('equipment.certificate', 'parent_id', string='Sub-items')
    child_count = fields.Integer(compute='_compute_child_count')
    complete_name = fields.Char(compute='_compute_complete_name', store=True, recursive=True)
    description = fields.Html(sanitize_attributes=False)
    active = fields.Boolean(default=True)

    @api.depends('name', 'parent_id.complete_name')
    def _compute_complete_name(self):
        for rec in self:
            if rec.parent_id:
                rec.complete_name = f'{rec.parent_id.complete_name} / {rec.name}'
            else:
                rec.complete_name = rec.name

    def _compute_child_count(self):
        for rec in self:
            rec.child_count = len(rec.child_ids)

    @api.constrains('parent_id')
    def _check_parent_id(self):
        if not self._check_recursion():
            raise ValidationError('You cannot create recursive certificate trees.')

    @api.model
    def _name_search(self, name, domain=None, operator='ilike', limit=None, order=None):
        domain = domain or []
        if name:
            domain = ['|', ('name', operator, name), ('complete_name', operator, name)] + domain
        return self._search(domain, limit=limit, order=order)
