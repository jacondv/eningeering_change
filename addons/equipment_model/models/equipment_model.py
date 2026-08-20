from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class EquipmentModel(models.Model):
    """The abstract product design for one of the company's off-highway
    machines - not to be confused with `project.project` (a Job Number),
    which is a concrete customer order / production copy of a Model (see
    `project.project.model_id` in project_project.py).

    Models may inherit from a parent Model (`parent_id`), e.g. a variant
    built on top of a base machine design.
    """
    _name = 'equipment.model'
    _description = 'Equipment Model'
    _order = 'name'
    _parent_store = True

    name = fields.Char(required=True, index=True)
    description = fields.Text()
    family_id = fields.Many2one(
        'equipment.model.family', string='Product Family', index=True)
    parent_id = fields.Many2one(
        'equipment.model', string='Parent Model', index=True, ondelete='restrict')
    child_ids = fields.One2many('equipment.model', 'parent_id', string='Child Models')
    parent_path = fields.Char(index=True)
    project_ids = fields.One2many('project.project', 'model_id', string='Projects')
    active = fields.Boolean(default=True)

    @api.constrains('parent_id')
    def _check_parent_recursion(self):
        if not self._check_recursion():
            raise ValidationError(_("A Model cannot be its own ancestor."))
