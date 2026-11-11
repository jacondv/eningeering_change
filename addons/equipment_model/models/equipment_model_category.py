from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class EquipmentModelCategory(models.Model):
    """A product line (Model Group) grouping several Product Families, each
    of which in turn groups several Equipment Models - independent of the
    parent/child design-inheritance hierarchy on `equipment.model` itself.

    Also holds the running Job number its Jobs are named with, shared by all
    of its Product Families: see project.project.get_suggested_job_name.
    """
    _name = 'equipment.model.category'
    _description = 'Equipment Model Category'
    _order = 'name'

    name = fields.Char(required=True, index=True)
    description = fields.Text()
    family_ids = fields.One2many('equipment.model.family', 'category_id', string='Product Families')
    family_count = fields.Integer(compute='_compute_family_count')
    model_count = fields.Integer(compute='_compute_model_count')
    active = fields.Boolean(default=True)
    last_job_number = fields.Integer(
        string='Last Job Number',
        help="The number of this Group's latest Job: the next suggested Job name gets the one after it. "
             "Moves up by itself whenever a Job named <Product Family>-<number> is saved with a higher number.")
    job_number_digits = fields.Integer(
        string='Job Number Digits', default=3, required=True,
        help="How many digits Job numbers have, zero-padded: 3 gives S100-007.")

    _unique_name = models.UniqueIndex('(lower(name))', "A Group with this name already exists.")

    @api.constrains('job_number_digits')
    def _check_job_number_digits(self):
        for rec in self:
            if not 1 <= rec.job_number_digits <= 6:
                raise ValidationError(_("Job Number Digits must be between 1 and 6."))

    def _raise_last_job_number(self, number):
        """Move Last Job Number up to `number`, never down. Holds the Group until
        commit, so that two Jobs saved at once with the same new number go one
        after the other: the second is then stopped by the unique Project name
        check (jacon_core) instead of both passing it before either is committed.
        Whoever may save a Job moves the counter, Group editing rights or not."""
        self.ensure_one()
        self.env.cr.execute("SELECT last_job_number FROM equipment_model_category WHERE id = %s FOR UPDATE", [self.id])
        if number > (self.env.cr.fetchone()[0] or 0):
            self.sudo().last_job_number = number

    def _fill_last_job_numbers(self):
        """Move each Group's Last Job Number up to the highest Job number already
        in use in any of its Product Families. Never lowers a number."""
        Project = self.env['project.project']
        for group in self:
            families = group.with_context(active_test=False).family_ids
            highest = max((number for _project, number in Project._job_numbers(families, group)), default=0)
            if highest > group.last_job_number:
                group._raise_last_job_number(highest)

    def _compute_family_count(self):
        for rec in self:
            rec.family_count = len(rec.family_ids)

    def _compute_model_count(self):
        for rec in self:
            rec.model_count = sum(len(family.model_ids) for family in rec.family_ids)
