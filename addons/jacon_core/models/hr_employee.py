from datetime import timedelta

from odoo import fields, models

DONE_TASK_STATES = ('1_done', '1_canceled')


def _group_overloaded_days(days):
    """Consecutive overloaded work days -> [{start, end, task_ids}], so the
    warning reads as one range ("12/8 -> 14/8") instead of one line per
    day. `days` is already sorted, work-days-only, so list-adjacency alone
    (not date arithmetic) is exactly "consecutive working days"."""
    groups = []
    current = None
    for day in days:
        if day['overloaded']:
            if current is None:
                current = {'start': day['date'], 'end': day['date'], 'task_ids': set(day['task_ids'])}
                groups.append(current)
            else:
                current['end'] = day['date']
                current['task_ids'] |= set(day['task_ids'])
        else:
            current = None
    return groups


class HrEmployee(models.Model):
    """Shared workload engine: how many hours of open task work an
    employee is carrying on each working day, against their
    working-calendar capacity. Used both by the Task form's overload
    warning (jacon_core) and, later, by the Hours Dashboard's capacity
    view (jacon_project_dashboard) - kept here so both call the same math
    instead of drifting apart.

    Every task has an explicit `date_start` (default: creation date) and
    `date_deadline`. Its `allocated_hours` (the planned/booked hours, NOT
    `remaining_hours`) is spread evenly across the working days in that
    window - a fixed, stored window, not "today" recomputed on every
    check, so the answer for a given task doesn't silently shift
    depending on which day you happen to look at it.

    `allocated_hours` is used on purpose instead of `remaining_hours`:
    this is a *schedule* (how much of each day is booked), not a
    progress tracker - logging timesheet hours against a task shouldn't
    instantly "free up" days that are still booked on the calendar until
    the task is actually closed (Done/Cancelled), at which point it
    drops out of this calculation entirely, regardless of how many hours
    it ended up taking.
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

    def get_period_capacity_hours(self, date_from, date_to):
        """Total working-hour capacity for this employee between
        date_from and date_to (inclusive) - daily hours x working days
        per their calendar (Mon-Fri unless configured otherwise).
        Company holidays and personal leave are not subtracted yet (no
        leave data in the system to subtract from) - this is a ceiling,
        not yet a true "how much room is left" figure."""
        self.ensure_one()
        date_from = fields.Date.to_date(date_from)
        date_to = fields.Date.to_date(date_to)
        weekdays = self._work_weekdays()
        return self._daily_hours() * self._count_work_days(date_from, date_to, weekdays)

    def _next_work_day(self, d, weekdays):
        while d.weekday() not in weekdays:
            d += timedelta(days=1)
        return d

    def get_daily_load(self, date_from, date_to, extra_remaining=None, exclude_task_id=None):
        """Per-work-day load vs. capacity for this employee, covering
        every working day in [date_from, date_to] (inclusive).

        Every open task assigned to this employee (state not
        done/canceled, with a deadline) spreads its `allocated_hours`
        evenly across the working days from its own `date_start` to its
        `date_deadline`, contributing that daily rate to each of those
        days that also falls inside [date_from, date_to].

        An overdue task (deadline already in the past) has no valid
        future window, so its full remaining load is dumped onto the
        nearest work day from today instead - it's debt the employee is
        carrying right now, not spread-out future work.

        `extra_remaining`: list of (remaining_hours, date_start, deadline)
        for tasks not yet saved (e.g. the one being edited on a form).
        """
        self.ensure_one()
        weekdays = self._work_weekdays()
        daily_hours = self._daily_hours()
        today = fields.Date.context_today(self)
        date_from = fields.Date.to_date(date_from)
        date_to = fields.Date.to_date(date_to)

        days = {}
        d = date_from
        while d <= date_to:
            if d.weekday() in weekdays:
                days[d] = {'date': d, 'load': 0.0, 'task_ids': set()}
            d += timedelta(days=1)

        def _distribute(remaining, start, deadline, task_id=None):
            if remaining <= 0 or not deadline:
                return
            deadline = fields.Date.to_date(deadline)
            start = fields.Date.to_date(start) or deadline
            if deadline < today:
                dump_day = self._next_work_day(today, weekdays)
                start, deadline = dump_day, dump_day
            elif start > deadline:
                start = deadline
            work_days = self._count_work_days(start, deadline, weekdays) or 1
            per_day = remaining / work_days
            d = max(start, date_from)
            end = min(deadline, date_to)
            while d <= end:
                if d in days:
                    days[d]['load'] += per_day
                    if task_id:
                        days[d]['task_ids'].add(task_id)
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
                task_start = task.date_start or task.create_date
                _distribute(max(task.allocated_hours or 0.0, 0.0), task_start, task.date_deadline, task.id)

        for remaining, start, deadline in (extra_remaining or []):
            _distribute(remaining, start, deadline)

        result = []
        for d in sorted(days):
            day = days[d]
            day['capacity'] = daily_hours
            day['load'] = round(day['load'], 1)
            day['free'] = round(daily_hours - day['load'], 1)
            day['overloaded'] = day['load'] > daily_hours + 0.01
            day['task_ids'] = list(day['task_ids'])
            result.append(day)
        return result

    def get_overloaded_ranges(self, date_from, date_to, extra_remaining=None, exclude_task_id=None):
        """`get_daily_load` + grouped into contiguous overloaded ranges -
        what the warning banner and conflict wizard actually display."""
        days = self.get_daily_load(date_from, date_to, extra_remaining=extra_remaining, exclude_task_id=exclude_task_id)
        return _group_overloaded_days(days)

    def suggest_deadline_without_overload(self, remaining_hours, date_start, after_date=None,
                                           exclude_task_id=None, horizon_days=180):
        """Nearest deadline (searching forward day by day from `after_date`,
        or from `date_start` if not given) such that spreading
        `remaining_hours` evenly across working days from `date_start` to
        that candidate deadline keeps every day's combined load (this
        task + this employee's other open tasks) within daily capacity.
        None if nothing works within `horizon_days`. Only a suggestion:
        the caller decides whether to apply it."""
        self.ensure_one()
        if remaining_hours <= 0:
            return None
        weekdays = self._work_weekdays()
        date_start = fields.Date.to_date(date_start) or fields.Date.context_today(self)
        search_from = fields.Date.to_date(after_date) or date_start
        d = search_from + timedelta(days=1)
        limit = search_from + timedelta(days=horizon_days)
        while d <= limit:
            if d.weekday() in weekdays:
                days = self.get_daily_load(
                    date_start, d,
                    extra_remaining=[(remaining_hours, date_start, d)],
                    exclude_task_id=exclude_task_id)
                if days and not any(day['overloaded'] for day in days):
                    return d
            d += timedelta(days=1)
        return None
