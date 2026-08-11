from datetime import timedelta

from odoo import fields, models

DONE_TASK_STATES = ('1_done', '1_canceled')


def _week_start(d):
    return d - timedelta(days=d.weekday())


class HrEmployee(models.Model):
    """Shared weekly-workload engine: how many hours of open task work an
    employee is carrying per week, against their working-calendar capacity.
    Used both by the Task form's overload warning (jacon_core) and, later,
    by the Hours Dashboard's capacity view (jacon_project_dashboard) - kept
    here so both call the same math instead of drifting apart.
    """
    _inherit = 'hr.employee'

    def _work_weekdays(self):
        """Set of 0=Monday..6=Sunday weekdays this employee's calendar has
        at least one attendance on. Falls back to Mon-Fri if no calendar is
        configured."""
        self.ensure_one()
        calendar = self.resource_calendar_id
        if not calendar or not calendar.attendance_ids:
            return {0, 1, 2, 3, 4}
        return {int(a.dayofweek) for a in calendar.attendance_ids}

    def _daily_hours(self):
        self.ensure_one()
        return self.resource_calendar_id.hours_per_day or 8.0

    def _count_work_days(self, date_from, date_to, weekdays):
        if date_to < date_from:
            return 0
        count = 0
        d = date_from
        while d <= date_to:
            if d.weekday() in weekdays:
                count += 1
            d += timedelta(days=1)
        return count

    def get_weekly_load(self, date_from, date_to, extra_remaining=None, exclude_task_id=None):
        """Weekly workload preview for this employee, covering the Mon-Sun
        weeks that overlap [date_from, date_to].

        Every open task assigned to this employee (state not done/canceled,
        with a deadline) has its `remaining_hours` (allocated - already
        logged) spread evenly across its working days from today to its
        deadline, and summed into whichever week bucket each of those days
        falls in - regardless of how close or far the deadline is, the
        window is always [today, deadline].

        An overdue task (deadline already in the past) has no valid
        [today, deadline] window, so its full remaining load is dumped into
        the current week instead - it's debt the employee is carrying right
        now, not spread-out future work.

        `extra_remaining`: list of (remaining_hours, deadline) pairs for
        tasks not yet saved (e.g. the one being edited on a form), merged
        in the same way.
        """
        self.ensure_one()
        weekdays = self._work_weekdays()
        daily_hours = self._daily_hours()
        today = fields.Date.context_today(self)
        # `date_deadline` is a Datetime field on project.task - normalize
        # any date/datetime/string that flows through here to a plain date.
        date_from = fields.Date.to_date(date_from)
        date_to = fields.Date.to_date(date_to)

        weeks = []
        cursor = _week_start(date_from)
        while cursor <= date_to:
            week_end = cursor + timedelta(days=6)
            weeks.append({
                'start': cursor,
                'end': week_end,
                'capacity': daily_hours * self._count_work_days(cursor, week_end, weekdays),
                'load': 0.0,
                'task_ids': set(),
            })
            cursor += timedelta(days=7)

        def _distribute(remaining, deadline, task_id=None):
            if remaining <= 0 or not deadline:
                return
            start, end = today, fields.Date.to_date(deadline)
            if end < today:
                start, end = today, _week_start(today) + timedelta(days=6)
            work_days = self._count_work_days(start, end, weekdays) or 1
            per_day = remaining / work_days
            d = start
            while d <= end:
                if d.weekday() in weekdays:
                    for week in weeks:
                        if week['start'] <= d <= week['end']:
                            week['load'] += per_day
                            if task_id:
                                week['task_ids'].add(task_id)
                            break
                d += timedelta(days=1)

        if self.user_id:
            domain = [
                ('user_ids', 'in', self.user_id.id),
                ('state', 'not in', list(DONE_TASK_STATES)),
                ('date_deadline', '!=', False),
            ]
            if exclude_task_id:
                domain.append(('id', '!=', exclude_task_id))
            for task in self.env['project.task'].search(domain):
                _distribute(max(task.remaining_hours or 0.0, 0.0), task.date_deadline, task.id)

        for remaining, deadline in (extra_remaining or []):
            _distribute(remaining, deadline)

        for week in weeks:
            week['load'] = round(week['load'], 1)
            week['free'] = round(week['capacity'] - week['load'], 1)
            week['overloaded'] = week['load'] > week['capacity'] + 0.01
            week['task_ids'] = list(week['task_ids'])
        return weeks

    def suggest_free_week_deadline(self, remaining_hours, after_date, exclude_task_id=None, horizon_weeks=12):
        """Nearest week (searching forward from the week after `after_date`)
        where this employee still has enough free capacity for
        `remaining_hours` - returned as that week's last working day. None
        if nothing frees up within `horizon_weeks`. Only a suggestion: the
        caller decides whether to apply it."""
        self.ensure_one()
        weekdays = self._work_weekdays()
        start = _week_start(fields.Date.to_date(after_date)) + timedelta(days=7)
        end = start + timedelta(weeks=horizon_weeks)
        for week in self.get_weekly_load(start, end, exclude_task_id=exclude_task_id):
            if week['free'] >= remaining_hours:
                work_days_in_week = [
                    week['start'] + timedelta(days=i) for i in range(7)
                    if (week['start'] + timedelta(days=i)).weekday() in weekdays
                ]
                if work_days_in_week:
                    return max(work_days_in_week)
        return None
