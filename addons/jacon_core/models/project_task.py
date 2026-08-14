from datetime import datetime

from odoo import api, fields, models

from .hr_employee import _priority_value

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

    # Defaults to today (creation date) but is editable - e.g. push it out
    # if the task can't realistically start right away. Drives the
    # overload calculation below: allocated_hours spreads evenly across
    # working days from here to date_deadline, a fixed window rather than
    # always "today", so the answer for a given task doesn't shift
    # depending on which day you happen to check it.
    date_start = fields.Date(string='Start Date', default=lambda self: fields.Date.context_today(self))

    # Never persisted - recomputed every time the form loads/reloads (not
    # just while editing), so it reflects the real, current state of every
    # other task in the system - e.g. it only clears after the overload
    # wizard's Save actually resolves the conflict, not just because the
    # wizard closed. See hr.employee.get_daily_load.
    overload_warning = fields.Text(
        string='Overload Warning', compute='_compute_overload_warning', store=False)

    # Never persisted, same reasoning as overload_warning above - a
    # separate check from it, though: overload_warning flags a day in
    # [date_start, date_deadline] that's paying down UNRELATED overdue
    # debt (see hr.employee._simulate_schedule), which says nothing
    # about whether THIS task's own hours actually fit in that window.
    # This one answers that directly via check_task_overload, so a brand
    # new task gets a concrete "here's a start date that works" instead
    # of only a vague "somewhere in here is tight" warning.
    suggested_start_notice = fields.Text(
        string='Suggested Start Date', compute='_compute_suggested_start', store=False)
    suggested_date_start = fields.Date(compute='_compute_suggested_start', store=False)
    suggested_date_deadline = fields.Datetime(compute='_compute_suggested_start', store=False)

    @api.depends('evidence_ids')
    def _compute_evidence_count(self):
        for rec in self:
            rec.evidence_count = len(rec.evidence_ids)

    def _get_assigned_employees(self):
        return self.env['hr.employee'].search([('user_id', 'in', self.user_ids.ids)])

    def _suggest_or_keep_deadline(self):
        """Nearest deadline this task's assignee has room for, or the
        task's current deadline if none was found within the search
        horizon - used to pre-fill the overload wizard's "New Deadline"
        column so it already opens on a sensible date instead of the one
        causing the overload."""
        self.ensure_one()
        employee = self._get_assigned_employees()[:1]
        allocated = max(self.allocated_hours or 0.0, 0.0)
        if employee and allocated:
            suggested = employee.suggest_deadline_without_overload(
                allocated, self.date_start, after_date=self.date_deadline, exclude_task_id=self.id,
                priority=_priority_value(self.priority))
            if suggested:
                time_of_day = (self.date_deadline or fields.Datetime.now()).time()
                return datetime.combine(suggested, time_of_day)
        return self.date_deadline

    def _get_overloaded_ranges(self):
        """(employee, day-range) pairs where this task's assignee(s) would
        be over daily capacity somewhere between this task's start and
        deadline, counting this task's own allocated hours on top of
        their other open tasks - shared by the warning banner and the
        conflict wizard so the two never disagree."""
        self.ensure_one()
        allocated = max(self.allocated_hours or 0.0, 0.0)
        if not (self.user_ids and allocated and self.date_deadline):
            return []
        start = self.date_start or fields.Date.context_today(self)
        exclude_id = self._origin.id or None
        result = []
        for employee in self._get_assigned_employees():
            ranges = employee.get_overloaded_ranges(
                start, self.date_deadline,
                extra_remaining=[(allocated, start, self.date_deadline, _priority_value(self.priority))],
                exclude_task_id=exclude_id)
            result += [(employee, rng) for rng in ranges]
        return result

    @api.depends('user_ids', 'allocated_hours', 'date_start', 'date_deadline')
    def _compute_overload_warning(self):
        for task in self:
            lines = []
            for employee, rng in task._get_overloaded_ranges():
                period = (
                    rng['start'].strftime('%d-%m') if rng['start'] == rng['end']
                    else '%s → %s' % (rng['start'].strftime('%d-%m'), rng['end'].strftime('%d-%m')))
                lines.append('%s - %s: over capacity by %.1fh' % (
                    employee.name, period, rng['excess_hours']))
            task.overload_warning = '\n'.join(lines) if lines else False

    @api.depends('user_ids', 'allocated_hours', 'date_start', 'date_deadline', 'priority')
    def _compute_suggested_start(self):
        for task in self:
            task.suggested_start_notice = False
            task.suggested_date_start = False
            task.suggested_date_deadline = False
            allocated = max(task.allocated_hours or 0.0, 0.0)
            if not (task.user_ids and allocated and task.date_deadline):
                continue
            employee = task._get_assigned_employees()[:1]
            if not employee:
                continue
            start = task.date_start or fields.Date.context_today(task)
            deadline = fields.Date.to_date(task.date_deadline)
            if start > deadline:
                start = deadline
            exclude_id = task._origin.id or None
            priority = _priority_value(task.priority)
            base_queue = employee._task_queue()
            if not employee.check_task_overload(
                    allocated, start, deadline, priority=priority, exclude_task_id=exclude_id,
                    base_queue=base_queue):
                continue
            weekdays = employee._work_weekdays()
            duration_work_days = employee._count_work_days(start, deadline, weekdays) or 1
            suggestion = employee.suggest_start_without_overload(
                allocated, duration_work_days, priority=priority,
                after_date=start, exclude_task_id=exclude_id, base_queue=base_queue)
            if not suggestion:
                continue
            new_start, new_deadline = suggestion
            task.suggested_date_start = new_start
            time_of_day = (task.date_deadline or fields.Datetime.now()).time()
            task.suggested_date_deadline = datetime.combine(new_deadline, time_of_day)
            task.suggested_start_notice = (
                'Starting %s would overload %s - they wouldn\'t finish this task in time. '
                'Suggested: %s → %s (same length, next slot with room).' % (
                    start.strftime('%d-%m-%Y'), employee.name,
                    new_start.strftime('%d-%m'), new_deadline.strftime('%d-%m-%Y')))

    def action_apply_suggested_start(self):
        for task in self:
            if task.suggested_date_start and task.suggested_date_deadline:
                task.write({
                    'date_start': task.suggested_date_start,
                    'date_deadline': task.suggested_date_deadline,
                })

    def action_view_overload_conflicts(self):
        """Open a review wizard (not a direct edit) for the other open
        tasks contributing to this task's overload - deadlines are only
        applied to the real tasks if the user clicks Save on the wizard."""
        self.ensure_one()
        task_ids = set()
        for _employee, rng in self._get_overloaded_ranges():
            task_ids.update(rng['task_ids'])
        conflicts = self.env['project.task'].browse(task_ids)
        wizard = self.env['jacon.task.deadline.wizard'].create({
            'line_ids': [
                (0, 0, {'task_id': task.id, 'new_deadline': task._suggest_or_keep_deadline()})
                for task in conflicts
            ],
        })
        return {
            'type': 'ir.actions.act_window',
            'name': 'Tasks in Schedule Conflict',
            'res_model': 'jacon.task.deadline.wizard',
            'view_mode': 'form',
            'res_id': wizard.id,
            'target': 'new',
        }
