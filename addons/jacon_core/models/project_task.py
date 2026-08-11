from odoo import api, fields, models

TASK_TYPE_SELECTION = [
    ('3d', '3D'),
    ('2d', '2D'),
    ('sch', 'Sch'),
    ('bom', 'BOM'),
    ('checklist', 'Checklist'),
    ('doc', 'Doc'),
    ('fem', 'FEM'),
    ('rnd', 'R&D'),
    ('train', 'Train'),
    ('prog', 'Prog'),
    ('hyd', 'Hyd'),
    ('mnf', 'M&F'),
    ('cal', 'Cal'),
    ('test', 'Test'),
    ('s_manual', 'S-Manual'),
    ('m_manual', 'M-Manual'),
    ('o_manual', 'O-Manual'),
]


class ProjectTask(models.Model):
    _inherit = 'project.task'

    # Default to the creating user - core only does this when created from
    # a "My Tasks" personal-stage context, not from a Project's Tasks list.
    user_ids = fields.Many2many(default=lambda self: self.env.user.ids)

    task_type = fields.Selection(
        TASK_TYPE_SELECTION, string='Task Type', index=True, tracking=True)

    evidence_ids = fields.One2many(
        'engineering.change.action.evidence', 'task_id', string='Evidence')
    evidence_count = fields.Integer(compute='_compute_evidence_count')

    # Session-only warning, never persisted - set by `_onchange_check_overload`
    # while the form is being edited (see hr.employee.get_weekly_load).
    overload_warning = fields.Text(string='Overload Warning', store=False)

    @api.depends('evidence_ids')
    def _compute_evidence_count(self):
        for rec in self:
            rec.evidence_count = len(rec.evidence_ids)

    def _get_assigned_employees(self):
        return self.env['hr.employee'].search([('user_id', 'in', self.user_ids.ids)])

    @api.onchange('user_ids', 'allocated_hours', 'date_deadline')
    def _onchange_check_overload(self):
        self.overload_warning = False
        if not (self.user_ids and self.allocated_hours and self.date_deadline):
            return
        remaining = max(self.remaining_hours or 0.0, 0.0)
        if not remaining:
            return
        exclude_id = self._origin.id or None
        today = fields.Date.context_today(self)
        lines = []
        for employee in self._get_assigned_employees():
            weeks = employee.get_weekly_load(
                today, self.date_deadline,
                extra_remaining=[(remaining, self.date_deadline)],
                exclude_task_id=exclude_id)
            for week in weeks:
                if week['overloaded']:
                    lines.append('%s - tuần %s → %s: %.1fh / %.1fh (vượt %.1fh)' % (
                        employee.name,
                        week['start'].strftime('%d-%m'), week['end'].strftime('%d-%m'),
                        week['load'], week['capacity'], week['load'] - week['capacity']))
        if lines:
            self.overload_warning = '\n'.join(lines)

    def action_view_overload_conflicts(self):
        """Open a review wizard (not a direct edit) for the other open
        tasks contributing to this task's overload - deadlines are only
        applied to the real tasks if the user clicks Save on the wizard."""
        self.ensure_one()
        remaining = max(self.remaining_hours or 0.0, 0.0)
        today = fields.Date.context_today(self)
        task_ids = set()
        for employee in self._get_assigned_employees():
            weeks = employee.get_weekly_load(
                today, self.date_deadline,
                extra_remaining=[(remaining, self.date_deadline)],
                exclude_task_id=self.id)
            for week in weeks:
                if week['overloaded']:
                    task_ids.update(week['task_ids'])
        conflicts = self.env['project.task'].browse(task_ids)
        wizard = self.env['jacon.task.deadline.wizard'].create({
            'line_ids': [
                (0, 0, {'task_id': task.id, 'new_deadline': task.date_deadline})
                for task in conflicts
            ],
        })
        return {
            'type': 'ir.actions.act_window',
            'name': 'Task đang xung đột lịch',
            'res_model': 'jacon.task.deadline.wizard',
            'view_mode': 'form',
            'res_id': wizard.id,
            'target': 'new',
        }
