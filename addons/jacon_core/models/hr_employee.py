from collections import defaultdict
from datetime import datetime, time, timedelta

from pytz import timezone, utc

from odoo import fields, models

DONE_TASK_STATES = ('1_done', '1_canceled')


def _priority_value(priority):
    """project.task.priority is a string Selection ('0'..'3', Low..Urgent) -
    normalize to int for sorting/comparison, defaulting unset/unknown
    values to the lowest tier rather than raising."""
    try:
        return int(priority or '0')
    except (TypeError, ValueError):
        return 0


def _group_overloaded_days(days):
    """Consecutive overloaded work days -> [{start, end, task_ids,
    excess_hours}], so the warning reads as one range ("12/8 -> 14/8")
    instead of one line per day. `excess_hours` is the total debt load
    across that range (see `_simulate_schedule`'s docstring for what
    "debt" means under the priority-queue model), so the warning can say
    *how much* over, not just that it's over. `days` is already sorted,
    work-days-only, so list-adjacency alone (not date arithmetic) is
    exactly "consecutive working days"."""
    groups = []
    current = None
    for day in days:
        if day['overloaded']:
            excess = day['debt_hours']
            if current is None:
                current = {
                    'start': day['date'], 'end': day['date'],
                    'task_ids': set(day['task_ids']), 'excess_hours': excess,
                }
                groups.append(current)
            else:
                current['end'] = day['date']
                current['task_ids'] |= set(day['task_ids'])
                current['excess_hours'] = round(current['excess_hours'] + excess, 1)
        else:
            current = None
    return groups


class HrEmployee(models.Model):
    """Shared workload engine: how many hours of open task work an
    employee is carrying, against their working-calendar capacity. Used
    both by the Task form's overload warning (jacon_core) and by the
    Hours Dashboard's Capacity/Workload/Task Timeline views
    (jacon_project_dashboard) - kept here so both call the same math
    instead of drifting apart.

    Modeled as a single-resource, priority-ordered queue (like a real
    person actually works: one task at a time, not a little of everything
    every day) rather than spreading each task's `allocated_hours` evenly
    in parallel across its own [date_start, date_deadline] window. Each
    open work day's capacity is handed to the highest-priority
    not-yet-finished task first (project.task.priority), ties broken by
    earliest deadline (EDD - the task with less slack goes first), then by
    shortest remaining hours (SPT) if even the deadline matches. A task
    that doesn't get all its hours scheduled by its own deadline is
    "overloaded" - see `_simulate_schedule`.

    Each task contributes `remaining_hours` (allocated_hours minus hours
    already logged via timesheet, floored at 0 - see project.task's own
    `remaining_hours`), not the full `allocated_hours` - a task that's
    mostly done shouldn't keep claiming its original full booking once
    real progress has been logged against it. This trusts timesheet
    entries as a genuine progress signal; it does NOT distinguish "logged
    hours that reflect real completed work" from "logged hours that
    don't" (e.g. time booked against the wrong day) - if that ever
    becomes a problem in practice, revisit this. A task only drops out of
    this calculation entirely once it's actually closed (Done/Cancelled).
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
        per their calendar (Mon-Fri unless configured otherwise), minus
        public holidays and personal time off - see
        `_unavailable_hours_by_day`."""
        self.ensure_one()
        date_from = fields.Date.to_date(date_from)
        date_to = fields.Date.to_date(date_to)
        weekdays = self._work_weekdays()
        daily_hours = self._daily_hours()
        leave_hours = self._unavailable_hours_by_day(date_from, date_to)
        total = 0.0
        d = date_from
        while d <= date_to:
            if d.weekday() in weekdays:
                total += max(daily_hours - leave_hours.get(d, 0.0), 0.0)
            d += timedelta(days=1)
        return total

    def _unavailable_hours_by_day(self, date_from, date_to):
        """{date: hours unavailable that day} for public holidays and
        this employee's personal time off in [date_from, date_to] - fed
        into `_simulate_schedule` so both the overload warning and the
        Task Timeline stop assuming every working day is fully open.

        Two sources, because Odoo only materializes a
        `resource.calendar.leaves` row (the exact, hour-precise
        record - half-days included) once a request is actually
        APPROVED (`hr.leave.action_validate` -> `_create_resource_leave`):
        - Public holidays (no resource_id) and this employee's own
          already-approved leave (state 'validate') both come from
          `resource.calendar.leaves` via `_leave_intervals_batch`,
          hour-exact.
        - Requests still awaiting approval ('confirm'/'validate1') have
          no such row yet, so they're read straight from `hr.leave` and
          treated as a full day off for each working day they touch -
          the exact half-day split isn't final until approved anyway,
          and this is a forward-looking warning, not payroll. Draft and
          refused/cancelled requests are ignored either way."""
        self.ensure_one()
        calendar = self.resource_calendar_id
        if not calendar or not self.resource_id:
            return {}
        tz = timezone(calendar.tz or self.tz or 'UTC')
        start_dt = tz.localize(datetime.combine(date_from, time.min))
        end_dt = tz.localize(datetime.combine(date_to + timedelta(days=1), time.min))

        hours = defaultdict(float)
        intervals = calendar._leave_intervals_batch(
            start_dt, end_dt, resources=self.resource_id, tz=tz,
        ).get(self.resource_id.id, [])
        for start, stop, _leave in intervals:
            d = start.date()
            while d <= stop.date():
                day_start = max(start, tz.localize(datetime.combine(d, time.min)))
                day_end = min(stop, tz.localize(datetime.combine(d + timedelta(days=1), time.min)))
                if day_end > day_start:
                    hours[d] += (day_end - day_start).total_seconds() / 3600
                d += timedelta(days=1)

        weekdays = self._work_weekdays()
        daily_hours = self._daily_hours()
        pending = self.env['hr.leave'].search([
            ('employee_id', '=', self.id),
            ('state', 'in', ('confirm', 'validate1')),
            ('date_from', '<=', end_dt.astimezone(utc).replace(tzinfo=None)),
            ('date_to', '>=', start_dt.astimezone(utc).replace(tzinfo=None)),
        ])
        for leave in pending:
            d = max(fields.Date.to_date(leave.date_from), date_from)
            last = min(fields.Date.to_date(leave.date_to), date_to)
            while d <= last:
                if d.weekday() in weekdays:
                    hours[d] = max(hours[d], daily_hours)
                d += timedelta(days=1)

        return hours

    def _task_queue(self):
        """Base priority-queue entries (task, remaining, start, deadline,
        priority) for every one of this employee's open tasks with a
        deadline - the same entries `_simulate_schedule` would build
        itself, but independent of any date window or `exclude_task_id`,
        so it's safe to compute ONCE and hand to many `_simulate_schedule`
        calls via `base_queue` (see there) instead of re-querying the
        database on every one - suggest_deadline_without_overload and
        suggest_start_without_overload each call _simulate_schedule in a
        day-by-day search loop (up to horizon_days times), and without
        this a fresh `project.task.search()` fired on every single
        iteration was the dominant cost of loading the Task Timeline
        (one such loop per overloaded bar)."""
        self.ensure_one()
        queue = []
        if not self.user_id:
            return queue
        domain = [
            ('user_ids', 'in', self.user_id.id),
            ('state', 'not in', list(DONE_TASK_STATES)),
            ('date_deadline', '!=', False),
        ]
        for task in self.env['project.task'].search(domain):
            deadline = fields.Date.to_date(task.date_deadline)
            start = fields.Date.to_date(task.date_start) or deadline
            if start > deadline:
                start = deadline
            queue.append({
                'key': ('task', task.id),
                'remaining': max(task.remaining_hours or 0.0, 0.0),
                'start': start,
                'deadline': deadline,
                'priority': _priority_value(task.priority),
            })
        return queue

    def _simulate_schedule(self, date_from, date_to, extra_remaining=None, exclude_task_id=None, base_queue=None,
                            leave_hours=None):
        """Greedy, priority-ordered resource-leveling simulation - the
        single engine behind get_daily_load / get_overloaded_ranges /
        suggest_deadline_without_overload / get_task_overload.

        Every open task assigned to this employee (state not
        done/canceled, with a deadline) joins one queue, sorted by
        (priority desc, deadline asc, remaining hours asc) - see the
        class docstring for why. Each work day in [date_from, date_to]
        hands its capacity to queue entries in that order, in as many
        whole/partial days as each needs, before moving to the next.
        Entries are NOT limited to date_to for consuming capacity within
        the loop - a task already overdue (deadline before date_from)
        still queues up front (its deadline sorts earliest) and keeps
        eating into today's and future capacity until finished, exactly
        like real backlog does.

        Two results per entry:
        - Day-level: `debt_hours` = how much of that day's capacity went
          to a task whose deadline has already passed as of that day -
          time spent firefighting old backlog instead of fresh work. A
          day is `overloaded` if debt_hours > 0 - shown as the red cell
          on the Workload Gantt heatmap.
        - Task-level: `unfinished_hours` = how much of a task's own
          allocated_hours was still NOT scheduled by the time its own
          deadline day was reached (0 if it finished on time) - this is
          what actually flags a Task Timeline bar as overloaded, not
          "does the window contain a red day" (a red day can be pure debt
          from a *different*, unrelated overdue task).

        `extra_remaining`: list of (remaining_hours, date_start, deadline)
        or (remaining_hours, date_start, deadline, priority) tuples for
        tasks not yet saved (e.g. the one being edited on a form or a
        hypothetical deadline being tested) - priority defaults to 0
        (Low) if omitted. Returned as `extra_results`, a list in the same
        order, each {'unfinished_hours', 'overloaded'}.

        `base_queue`: a pre-built `_task_queue()` result, reused instead
        of querying the database again - see `_task_queue`'s docstring
        for why. `exclude_task_id` is applied to it in-memory (cheap),
        same effect as the domain-level exclude used when building the
        queue fresh.

        `leave_hours`: a pre-built `_unavailable_hours_by_day()` result,
        reused for the same reason as `base_queue` - callers that run
        this in a day-by-day search loop (suggest_deadline/
        suggest_start_without_overload) compute it once for the whole
        horizon instead of re-querying leaves on every iteration. Each
        working day's capacity is `daily_hours` minus that day's
        unavailable hours (floored at 0) - see
        `_unavailable_hours_by_day` for what counts as unavailable.
        """
        self.ensure_one()
        weekdays = self._work_weekdays()
        daily_hours = self._daily_hours()
        date_from = fields.Date.to_date(date_from)
        date_to = fields.Date.to_date(date_to)

        # A future-looking window (date_to hasn't passed yet) has to start
        # simulating from today, not from date_from if that's later still -
        # otherwise days between today and date_from are silently skipped,
        # and any overdue backlog in the queue (which keeps consuming
        # capacity on every day until finished, per the class docstring)
        # gets dumped entirely into date_from..date_to instead of being
        # worked off during the weeks in between like it really would be.
        # A brand new task starting a month from now would otherwise look
        # "overloaded" today by someone else's small, already-stale debt
        # that will obviously be cleared long before that task's own
        # window even begins. Purely historical windows (date_to already
        # in the past) are left alone - there's nothing to simulate ahead
        # of them.
        today = fields.Date.context_today(self)
        if date_to >= today and date_from > today:
            date_from = today

        if base_queue is None:
            base_queue = self._task_queue()
        if leave_hours is None:
            leave_hours = self._unavailable_hours_by_day(date_from, date_to)
        if exclude_task_id:
            exclude_key = ('task', exclude_task_id)
            queue = [dict(entry) for entry in base_queue if entry['key'] != exclude_key]
        else:
            queue = [dict(entry) for entry in base_queue]

        for index, entry in enumerate(extra_remaining or []):
            remaining, start, deadline = entry[0], entry[1], entry[2]
            priority = entry[3] if len(entry) > 3 else 0
            if remaining <= 0 or not deadline:
                continue
            deadline = fields.Date.to_date(deadline)
            start = fields.Date.to_date(start) or deadline
            if start > deadline:
                start = deadline
            queue.append({
                'key': ('extra', index),
                'remaining': remaining,
                'start': start,
                'deadline': deadline,
                'priority': priority,
            })

        queue.sort(key=lambda e: (-e['priority'], e['deadline'], e['remaining']))

        days = {}
        d = date_from
        while d <= date_to:
            if d.weekday() in weekdays:
                days[d] = {'date': d, 'load': 0.0, 'debt_hours': 0.0, 'task_ids': set()}
            d += timedelta(days=1)

        finish = {}
        for d in sorted(days):
            capacity = max(daily_hours - leave_hours.get(d, 0.0), 0.0)
            days[d]['capacity'] = capacity
            for entry in queue:
                if capacity <= 0.0001:
                    break
                if entry['remaining'] <= 0 or entry['start'] > d:
                    continue
                alloc = min(capacity, entry['remaining'])
                days[d]['load'] += alloc
                if entry['key'][0] == 'task':
                    days[d]['task_ids'].add(entry['key'][1])
                if entry['deadline'] < d:
                    days[d]['debt_hours'] += alloc
                entry['remaining'] -= alloc
                capacity -= alloc
            for entry in queue:
                if entry['deadline'] == d and entry['key'] not in finish:
                    finish[entry['key']] = round(entry['remaining'], 1)

        # Entries whose deadline fell before date_from never hit the
        # 'deadline == d' snapshot above (the window starts after their
        # deadline already passed) - best-effort snapshot as of the end
        # of this window instead, the most current answer this call can
        # give for "still not done".
        for entry in queue:
            if entry['key'] not in finish and entry['deadline'] <= date_to:
                finish[entry['key']] = round(entry['remaining'], 1)

        result_days = []
        for d in sorted(days):
            day = days[d]
            day['capacity'] = round(day['capacity'], 1)
            day['load'] = round(day['load'], 1)
            day['debt_hours'] = round(day['debt_hours'], 1)
            day['free'] = round(max(day['capacity'] - day['load'], 0.0), 1)
            day['overloaded'] = day['debt_hours'] > 0.01
            day['task_ids'] = list(day['task_ids'])
            result_days.append(day)

        task_results = {
            key[1]: {'unfinished_hours': v, 'overloaded': v > 0.01}
            for key, v in finish.items() if key[0] == 'task'
        }
        extra_results = []
        for index in range(len(extra_remaining or [])):
            v = finish.get(('extra', index), 0.0)
            extra_results.append({'unfinished_hours': v, 'overloaded': v > 0.01})

        return result_days, task_results, extra_results

    def get_daily_load(self, date_from, date_to, extra_remaining=None, exclude_task_id=None, base_queue=None):
        """Day-level view of `_simulate_schedule` - one entry per working
        day in [date_from, date_to], each with load/capacity/free/
        overloaded/debt_hours/task_ids. See the class and
        `_simulate_schedule` docstrings for what 'overloaded' means under
        the priority-queue model."""
        days, _task_results, _extra_results = self._simulate_schedule(
            date_from, date_to, extra_remaining=extra_remaining, exclude_task_id=exclude_task_id,
            base_queue=base_queue)
        return days

    def get_task_overload(self, date_from, date_to, exclude_task_id=None, base_queue=None):
        """Task-level view of `_simulate_schedule`: {task_id:
        {'unfinished_hours', 'overloaded'}} for every one of this
        employee's open tasks whose deadline falls within [date_from,
        date_to] - the task-level counterpart to get_daily_load's
        day-level view, used to flag individual overloaded Task Timeline
        bars (a task is overloaded because IT didn't finish on time, not
        because some unrelated overdue task made a day in its window
        red)."""
        self.ensure_one()
        _days, task_results, _extra_results = self._simulate_schedule(
            date_from, date_to, exclude_task_id=exclude_task_id, base_queue=base_queue)
        return task_results

    def check_task_overload(self, remaining_hours, date_start, date_deadline, priority=0, exclude_task_id=None,
                             base_queue=None):
        """Would a task needing `remaining_hours`, running [date_start,
        date_deadline], finish on time once queued by `priority` alongside
        this employee's other open tasks - the same task-level check
        `get_task_overload` reports for tasks that already exist in the
        database, exposed here for one that doesn't (e.g. still being
        filled out on a form, not saved yet) so its own placement can be
        validated before it's created. True if it wouldn't finish in
        time."""
        self.ensure_one()
        if remaining_hours <= 0 or not date_deadline:
            return False
        date_start = fields.Date.to_date(date_start) or fields.Date.context_today(self)
        date_deadline = fields.Date.to_date(date_deadline)
        if date_start > date_deadline:
            date_start = date_deadline
        _days, _task_results, extra_results = self._simulate_schedule(
            date_start, date_deadline,
            extra_remaining=[(remaining_hours, date_start, date_deadline, priority)],
            exclude_task_id=exclude_task_id, base_queue=base_queue)
        return bool(extra_results and extra_results[0]['overloaded'])

    def get_overloaded_ranges(self, date_from, date_to, extra_remaining=None, exclude_task_id=None, base_queue=None):
        """`get_daily_load` + grouped into contiguous overloaded (debt)
        ranges - what the warning banner and conflict wizard actually
        display."""
        days = self.get_daily_load(
            date_from, date_to, extra_remaining=extra_remaining, exclude_task_id=exclude_task_id,
            base_queue=base_queue)
        return _group_overloaded_days(days)

    def suggest_deadline_without_overload(self, remaining_hours, date_start, after_date=None,
                                           exclude_task_id=None, horizon_days=180, priority=0, base_queue=None):
        """Nearest deadline (searching forward day by day from `after_date`,
        or from `date_start` if not given) such that, queued alongside
        this employee's other open tasks by priority, `remaining_hours`
        of work actually finishes by that candidate deadline - not merely
        "no day in the window is flagged overloaded" (day-level
        `overloaded` now means debt from OTHER, unrelated overdue tasks,
        which moving this one wouldn't fix or cause - see
        `_simulate_schedule`). `priority` should match the task's own
        priority so the search reflects how it will really queue against
        same/higher-priority work. None if nothing works within
        `horizon_days`. Only a suggestion: the caller decides whether to
        apply it.

        `base_queue`: precomputed once (via `_task_queue`) if not given,
        then reused across every iteration of the day-by-day search below
        instead of re-querying the database each time - see
        `_task_queue`'s docstring."""
        self.ensure_one()
        if remaining_hours <= 0:
            return None
        weekdays = self._work_weekdays()
        date_start = fields.Date.to_date(date_start) or fields.Date.context_today(self)
        search_from = fields.Date.to_date(after_date) or date_start
        d = search_from + timedelta(days=1)
        limit = search_from + timedelta(days=horizon_days)
        if base_queue is None:
            base_queue = self._task_queue()
        leave_hours = self._unavailable_hours_by_day(date_start, limit)
        while d <= limit:
            if d.weekday() in weekdays:
                _days, _task_results, extra_results = self._simulate_schedule(
                    date_start, d,
                    extra_remaining=[(remaining_hours, date_start, d, priority)],
                    exclude_task_id=exclude_task_id, base_queue=base_queue, leave_hours=leave_hours)
                if extra_results and not extra_results[0]['overloaded']:
                    return d
            d += timedelta(days=1)
        return None

    def _add_work_days(self, start_date, weekdays, count):
        """`count` working days after (not including) `start_date`, per
        `weekdays` - count=0 returns `start_date` itself unchanged."""
        d = start_date
        remaining = count
        while remaining > 0:
            d += timedelta(days=1)
            if d.weekday() in weekdays:
                remaining -= 1
        return d

    def suggest_start_without_overload(self, remaining_hours, duration_work_days, priority=0,
                                        after_date=None, exclude_task_id=None, horizon_days=180,
                                        base_queue=None):
        """Nearest (start, deadline) pair - searching forward day by day
        from `after_date` - such that a task needing `remaining_hours`
        across exactly `duration_work_days` working days, queued by
        `priority` alongside this employee's other open tasks, finishes
        on time. Unlike `suggest_deadline_without_overload` (which keeps
        the task's start fixed and stretches its deadline out, spreading
        the same hours thinner), this keeps the task's own length fixed
        and instead moves the WHOLE task later to the next slot where it
        actually fits - the Task Timeline's "Apply suggested deadline"
        repositions a task rather than dragging its deadline out. None if
        nothing works within `horizon_days`.

        Each candidate is simulated from TODAY (not from the candidate
        start itself) through the candidate deadline - a window starting
        at the candidate date would reset every other open task's
        remaining hours back to their full amount as of that day, as if
        no work had happened before it, making the same backlog look
        freshly full on every single candidate and never leaving room for
        this one. Starting from today each time lets that backlog
        realistically clear via capacity spent on the days before the
        candidate, exactly like `suggest_deadline_without_overload`
        does by keeping its window's start fixed while only the end
        grows.

        `base_queue`: precomputed once (via `_task_queue`) if not given,
        then reused across every iteration of the day-by-day search below
        instead of re-querying the database each time - see
        `_task_queue`'s docstring. Especially important here: the Task
        Timeline calls this once per overloaded bar, so without reuse
        each employee could trigger dozens/hundreds of redundant
        searches on a single dashboard load."""
        self.ensure_one()
        if remaining_hours <= 0 or duration_work_days <= 0:
            return None
        weekdays = self._work_weekdays()
        today = fields.Date.context_today(self)
        after_date = fields.Date.to_date(after_date) or today
        d = after_date + timedelta(days=1)
        limit = after_date + timedelta(days=horizon_days)
        if base_queue is None:
            base_queue = self._task_queue()
        # duration_work_days worth of extra slack so a candidate deadline
        # near the horizon's edge still has its leave data available.
        leave_hours = self._unavailable_hours_by_day(
            today, limit + timedelta(days=duration_work_days * 2 + 7))
        while d <= limit:
            if d.weekday() in weekdays:
                candidate_deadline = self._add_work_days(d, weekdays, duration_work_days - 1)
                _days, _task_results, extra_results = self._simulate_schedule(
                    today, candidate_deadline,
                    extra_remaining=[(remaining_hours, d, candidate_deadline, priority)],
                    exclude_task_id=exclude_task_id, base_queue=base_queue, leave_hours=leave_hours)
                if extra_results and not extra_results[0]['overloaded']:
                    return d, candidate_deadline
            d += timedelta(days=1)
        return None
