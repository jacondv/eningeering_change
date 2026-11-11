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

    _unique_name = models.UniqueIndex('(lower(name))', "A Model with this name already exists.")

    @api.constrains('parent_id')
    def _check_parent_recursion(self):
        if not self._check_recursion():
            raise ValidationError(_("A Model cannot be its own ancestor."))

    def _effective_family(self):
        """Its own Product Family, or else the nearest parent Model's."""
        self.ensure_one()
        model = self
        while model and not model.family_id:
            model = model.parent_id
        return model.family_id

    @api.model
    def get_dashboard_data(self):
        """What the Equipment Models dashboard (equipment_model_dashboard.js)
        shows: every Group, Product Family and Model with its counts, for the
        page to filter between. Only what the user can see is counted.

        A Model without a Product Family of its own is counted under its parent
        Model's, as Job names and the import do (_effective_family)."""
        Project = self.env['project.project']
        job_domain = Project._equipment_job_domain()
        jobs_per_model = {
            model.id: count
            for model, count in Project._read_group(job_domain + [('model_id', '!=', False)], ['model_id'], ['__count'])
        }
        families = self.env['equipment.model.family'].search([])
        family_group = {family.id: family.category_id.id for family in families}

        models = []
        for model in self.search([]):
            family_id = model._effective_family().id
            models.append({
                'id': model.id,
                'name': model.name,
                'parent': model.parent_id.name or '',
                'family_id': family_id,
                'group_id': family_group.get(family_id, 0),
                'jobs': jobs_per_model.get(model.id, 0),
            })

        def counts(key, value):
            own = [model for model in models if model[key] == value]
            return {'models': len(own), 'jobs': sum(model['jobs'] for model in own)}

        family_rows = [{
            'id': family.id, 'name': family.name, 'group_id': family.category_id.id,
            **counts('family_id', family.id),
        } for family in families]
        unassigned = counts('family_id', 0)
        if unassigned['models']:
            # Id 0 stands for "no Product Family", so that these Models can be reached too.
            family_rows.append({'id': 0, 'name': _("No Product Family"), 'group_id': 0, **unassigned})

        groups = [{
            'id': group.id,
            'name': group.name,
            'last_job_number': group.last_job_number,
            'families': len(group.family_ids),
            **counts('group_id', group.id),
        } for group in self.env['equipment.model.category'].search([])]
        return {
            'totals': {
                'groups': len(groups),
                'families': len(families),
                'models': len(models),
                'jobs': Project.search_count(job_domain),
            },
            'jobs_without_model': Project.search_count(job_domain + [('model_id', '=', False)]),
            'groups': groups,
            'families': family_rows,
            'models': models,
            'job_domain': job_domain,
        }
