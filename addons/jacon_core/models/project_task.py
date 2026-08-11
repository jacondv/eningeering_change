from datetime import datetime

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

    # Never persisted - recomputed every time the form loads/reloads (not
    # just while editing), so it reflects the real, current state of every
    # other task in the system - e.g. it only clears after the overload
    # wizard's Save actually resolves the conflict, not just because the
    # wizard closed. See hr.employee.get_weekly_load.
    overload_warning = fields.Text(
        string='Overload Warning', compute='_compute_overload_warning', store=False)

    @api.depends('evidence_ids')
    def _compute_evidence_count(self):
        for rec in self:
            rec.evidence_count = len(rec.evidence_ids)

    def _get_assigned_employees(self):
        return self.env['hr.employee'].search([('user_id', 'in', self.user_ids.ids)])

    def _suggest_or_keep_deadline(self):
        """Nearest week this task's assignee has room for it, or the task's
        current deadline if none was found - used to pre-fill the overload
        wizard's "New Deadline" column so it already opens on a sensible
        date instead of the one causing the overload."""
        self.ensure_one()
        employee = self._get_assigned_employees()[:1]
        remaining = max(self.remaining_hours or 0.0, 0.0)
        if employee and remaining:
            # A genuinely free week first (no other task touches it at all);
            # if this task alone needs more than a week's capacity, that can
            # never succeed, so fall back to a pace-based estimate instead
            # of silently giving up and leaving the deadline unchanged.
            suggested = (
                employee.suggest_free_week_deadline(remaining, self.date_deadline, exclude_task_id=self.id)
                or employee.suggest_paced_deadline(remaining, self.date_deadline)
            )
            if suggested:
                time_of_day = (self.date_deadline or fields.Datetime.now()).time()
                return datetime.combine(suggested, time_of_day)
        return self.date_deadline

    def _get_overloaded_weeks(self):
        """(employee, week) pairs where this task's assignee(s) would be
        over capacity, counting this task's own remaining hours on top of
        their other open tasks - shared by the warning banner and the
        conflict wizard so the two never disagree."""
        self.ensure_one()
        remaining = max(self.remaining_hours or 0.0, 0.0)
        if not (self.user_ids and self.allocated_hours and self.date_deadline and remaining):
            return []
        exclude_id = self._origin.id or None
        today = fields.Date.context_today(self)
        result = []
        for employee in self._get_assigned_employees():
            weeks = employee.get_weekly_load(
                today, self.date_deadline,
                extra_remaining=[(remaining, self.date_deadline)],
                exclude_task_id=exclude_id)
            result += [(employee, week) for week in weeks if week['overloaded']]
        return result

    @api.depends('user_ids', 'allocated_hours', 'date_deadline', 'remaining_hours')
    def _compute_overload_warning(self):
        for task in self:
            lines = [
                '%s - tuần %s → %s: %.1fh / %.1fh (vượt %.1fh)' % (
                    employee.name, week['start'].strftime('%d-%m'), week['end'].strftime('%d-%m'),
                    week['load'], week['capacity'], week['load'] - week['capacity'])
                for employee, week in task._get_overloaded_weeks()
            ]
            task.overload_warning = '\n'.join(lines) if lines else False

    def action_view_overload_conflicts(self):
        """Open a review wizard (not a direct edit) for the other open
        tasks contributing to this task's overload - deadlines are only
        applied to the real tasks if the user clicks Save on the wizard."""
        self.ensure_one()
        task_ids = set()
        for _employee, week in self._get_overloaded_weeks():
            task_ids.update(week['task_ids'])
        conflicts = self.env['project.task'].browse(task_ids)
        wizard = self.env['jacon.task.deadline.wizard'].create({
            'line_ids': [
                (0, 0, {'task_id': task.id, 'new_deadline': task._suggest_or_keep_deadline()})
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
