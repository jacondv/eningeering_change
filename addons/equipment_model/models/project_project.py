import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Domain
from odoo.tools import escape_psql


class ProjectProject(models.Model):
    """A Project (Job Number) is a concrete customer order - one production
    copy of an Equipment Model.

    Jobs are named <Product Family>-<number>, numbered across the whole Group
    the Family belongs to (equipment.model.category.last_job_number).
    """
    _inherit = 'project.project'

    model_id = fields.Many2one('equipment.model', string='Model')

    @api.model
    def _equipment_job_domain(self):
        """The Projects that are real Jobs, as counted by the dashboard.
        Addons with Projects of their own kind leave those out here."""
        return [('is_template', '=', False)]

    @api.model
    def get_suggested_job_name(self, model_id):
        """<Product Family>-<next number of its Group>, skipping any number a
        Job of the Group already has, whichever of its Families it belongs to.
        Only a suggestion: nothing is reserved until saved."""
        model = self.env['equipment.model'].browse(model_id).exists()
        if not model:
            raise UserError(_("Choose a Model first."))
        family = model._effective_family()
        if not family:
            raise UserError(_(
                "Model %(model)s has no Product Family, nor does any of its parent Models. "
                "Set one on the Model first.", model=model.name))
        group = family.category_id
        used = {number for _project, number in self._job_numbers(group.with_context(active_test=False).family_ids, group)}
        number = group.last_job_number + 1
        while number in used:
            number += 1
        return f"{family.name}-{str(number).zfill(group.job_number_digits)}"

    @api.model
    def _job_numbers(self, families, group):
        """(Job, number) for every Job named <Family>-<number>, whichever of
        `families` it is of - all found by one search."""
        if not families:
            return
        patterns = [self._job_name_pattern(family, group) for family in families]
        name_matches = Domain.OR([Domain('name', '=ilike', f"{escape_psql(family.name)}-%") for family in families])
        projects = self.with_context(active_test=False).search(
            Domain.AND([self._equipment_job_domain(), name_matches]))
        for project in projects:
            for pattern in patterns:
                match = pattern.match(project.name)
                if match:
                    yield project, int(match.group(1))
                    break

    @api.model
    def _job_name_pattern(self, family, group):
        # At least the Group's digits, so a Group that outgrows them (S100-999,
        # then S100-1000) keeps counting. Anything may follow the number:
        # "S100-265 (Hardware version)" is Job 265.
        return re.compile(rf"{re.escape(family.name)}-(\d{{{group.job_number_digits},}})", re.IGNORECASE)

    @api.model_create_multi
    def create(self, vals_list):
        projects = super().create(vals_list)
        projects._update_job_counters()
        return projects

    def write(self, vals):
        result = super().write(vals)
        if 'name' in vals or 'model_id' in vals:
            self._update_job_counters()
        return result

    def _update_job_counters(self):
        """A Job saved as <Family>-<number> above its Group's Last Job Number
        moves that number up to it, whether the name was suggested or typed.
        Any other name - a draft without a number yet - leaves it alone."""
        highest = {}
        for project in self:
            if project.is_template or not project.name or not project.model_id:
                continue
            family = project.model_id._effective_family()
            group = family.category_id
            match = group and self._job_name_pattern(family, group).match(project.name)
            if match:
                highest[group] = max(highest.get(group, 0), int(match.group(1)))
        # In a fixed order, so that two saves touching several Groups can't wait on each other.
        for group in sorted(highest, key=lambda group: group.id):
            if highest[group] > group.last_job_number:
                group._raise_last_job_number(highest[group])
