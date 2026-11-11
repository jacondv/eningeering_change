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
        """Counts for the Equipment Models dashboard (equipment_model_dashboard.js).
        Only what the user can see is counted, so a figure always matches the
        list its click opens."""
        Project = self.env['project.project']
        Family = self.env['equipment.model.family']
        job_domain = Project._equipment_job_domain()

        models_per_family = {
            family.id: count
            for family, count in self._read_group([], ['family_id'], ['__count'])
        }
        jobs_per_model = {
            model.id: count
            for model, count in Project._read_group(job_domain + [('model_id', '!=', False)], ['model_id'], ['__count'])
        }
        jobs_per_family = {}
        for model in self.browse(jobs_per_model):
            family = model.family_id.id
            jobs_per_family[family] = jobs_per_family.get(family, 0) + jobs_per_model[model.id]

        families = [{
            'id': family.id,
            'name': family.name,
            'group_id': family.category_id.id,
            'group': family.category_id.name,
            'models': models_per_family.get(family.id, 0),
            'jobs': jobs_per_family.get(family.id, 0),
        } for family in Family.search([])]
        groups = []
        for group in self.env['equipment.model.category'].search([]):
            own = [family for family in families if family['group_id'] == group.id]
            groups.append({
                'id': group.id,
                'name': group.name,
                'families': len(own),
                'models': sum(family['models'] for family in own),
                'jobs': sum(family['jobs'] for family in own),
                'last_job_number': group.last_job_number,
            })
        return {
            'totals': {
                'groups': len(groups),
                'families': len(families),
                'models': self.search_count([]),
                'jobs': Project.search_count(job_domain),
            },
            'attention': {
                'models_without_family': models_per_family.get(False, 0),
                'jobs_without_model': Project.search_count(job_domain + [('model_id', '=', False)]),
            },
            'groups': groups,
            'families': families,
            'job_domain': job_domain,
        }
