import calendar
from datetime import date

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.fields import Domain

from odoo.addons.jacon_core.models.hr_employee import _priority_value
from odoo.addons.jacon_core.models.project_task import TASK_TYPE_SELECTION

DONE_TASK_STATES = ('1_done', '1_canceled')
TASK_TYPE_LABELS = dict(TASK_TYPE_SELECTION)


def _month_label(value):
    """`_read_group` returns a `date` (first day of the month) for a
    'field:month' groupby key - format it as 'YYYY-MM' for the chart axis.
    Falls back to a plain string for any other shape, just in case."""
    if hasattr(value, 'strftime'):
        return value.strftime('%Y-%m')
    return str(value) if value else 'N/A'


def _num(value):
    """`_read_group` SUM aggregates can come back as `False` instead of
    `0.0` for some groups (NULL-coalescing gap) - normalize to a real
    number everywhere a summed value is used, so arithmetic never breaks."""
    return value or 0.0


def _rec_id_name(value):
    """A `_read_group` groupby row on a relational field is either an empty
    recordset (no value) or a single-record recordset - normalize both into
    a plain {id, name} dict (or None)."""
    if not value:
        return None
    return {'id': value.id, 'name': value.display_name}


def _month_bounds(year, month):
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


class JaconProjectDashboard(models.AbstractModel):
    """Pure aggregation logic backing the Jacon Project Dashboard client
    action - no table of its own (AbstractModel), same idea as
    `engineering.change.get_dashboard_data()` but factored into its own
    model since this dashboard isn't tied to one business model.
    """
    _name = 'jacon.project.dashboard'
    _description = 'Jacon Project Dashboard'

    @api.model
    def get_filter_options(self):
        projects = self.env['project.project'].search_read([], ['name'], order='name')
        employees = self.env['hr.employee'].search_read([], ['name'], order='name')

        current_year = fields.Date.context_today(self).year
        first_line = self.env['account.analytic.line'].search(
            [('project_id', '!=', False)], order='date asc', limit=1)
        min_year = first_line.date.year if first_line and first_line.date else current_year
        years = list(range(min_year, current_year + 1))

        months = [{'key': m, 'label': calendar.month_abbr[m]} for m in range(1, 13)]

        return {
            'projects': [{'id': p['id'], 'name': p['name']} for p in projects],
            'employees': [{'id': e['id'], 'name': e['name']} for e in employees],
            'task_types': [{'key': key, 'label': label} for key, label in TASK_TYPE_SELECTION],
            'years': years,
            'months': months,
            'current_year': current_year,
        }

    def _years_months_domain(self, years, months):
        """Both Year and Month are multi-select and independent of each
        other: every selected year is OR'd together, each optionally
        narrowed to the selected months (also OR'd) - e.g. Jan+Jul of
        2025 OR 2026, not a contiguous range."""
        year_domains = []
        for year in years:
            if months:
                month_domains = [
                    [('date', '>=', s.isoformat()), ('date', '<=', e.isoformat())]
                    for s, e in (_month_bounds(year, m) for m in months)
                ]
                year_domains.append(Domain.OR(month_domains))
            else:
                year_domains.append([
                    ('date', '>=', date(year, 1, 1).isoformat()),
                    ('date', '<=', date(year, 12, 31).isoformat())])
        return Domain.OR(year_domains)

    def _date_domain(self, filters):
        years = filters.get('years') or [fields.Date.context_today(self).year]
        months = filters.get('months') or []
        return self._years_months_domain(years, months)

    def _period_segments(self, filters):
        """(start, end) date pairs for the currently selected Year/Month
        filter - a list rather than one min..max span, because selected
        months can be non-contiguous (e.g. Jan + Jul) or span several
        years; summing capacity over a single wide range would wrongly
        include unselected months in between."""
        years = filters.get('years') or [fields.Date.context_today(self).year]
        months = filters.get('months') or []
        segments = []
        for year in years:
            if months:
                segments += [_month_bounds(year, m) for m in months]
            else:
                segments.append((date(year, 1, 1), date(year, 12, 31)))
        return segments

    def _period_segments_from_today(self, filters):
        """`_period_segments`, clamped so no segment starts before today -
        shared by Capacity and the Workload Gantt, both of which are
        forward-looking ("who has room / who's overloaded from now on"),
        not a record of what already happened."""
        today = fields.Date.context_today(self)
        segments = [(max(start, today), end) for start, end in self._period_segments(filters)]
        return [(start, end) for start, end in segments if start <= end]

    def _build_domains(self, filters):
        """Two separate domains: Spent (Timesheet, date-bounded) and Planned
        (Task, not date-bounded - `allocated_hours` is a single static
        number per task, it has no per-month breakdown to filter on)."""
        project_ids = filters.get('project_ids') or []
        employee_ids = filters.get('employee_ids') or []
        task_types = filters.get('task_types') or []

        spent_domain = Domain.AND([[('project_id', '!=', False)], self._date_domain(filters)])
        if project_ids:
            spent_domain = Domain.AND([spent_domain, [('project_id', 'in', project_ids)]])
        if employee_ids:
            spent_domain = Domain.AND([spent_domain, [('employee_id', 'in', employee_ids)]])
        if task_types:
            spent_domain = Domain.AND([spent_domain, [('task_type', 'in', task_types)]])

        planned_domain = [('project_id', '!=', False)]
        if project_ids:
            planned_domain.append(('project_id', 'in', project_ids))
        if employee_ids:
            user_ids = self.env['hr.employee'].browse(employee_ids).mapped('user_id').ids
            planned_domain.append(('user_ids', 'in', user_ids))
        if task_types:
            planned_domain.append(('task_type', 'in', task_types))

        return spent_domain, planned_domain

    def _capacity_by_employee(self, filters):
        """Calendar capacity for the selected Year/Month period vs how much
        of it is already committed to open tasks, so a manager can see who
        still has room *this period* for MORE work - not who has been busy
        in the past.

        Capacity = daily hours x working days across the selected period
        (Mon-Fri per each employee's calendar; company holidays and
        personal leave aren't subtracted yet - see
        hr.employee.get_period_capacity_hours - so this is currently a
        ceiling, slightly optimistic until leave data exists). Any part of
        the period that's already in the past is excluded from both sides
        - a day that's gone can't be "still free for more work", so
        counting it would only inflate the free% for periods partly
        behind us (e.g. viewing this month from the 20th).

        Committed is NOT "hours already logged" (that's a backward-looking
        fact that drops the instant someone logs a timesheet line, even
        though the task's calendar slot hasn't actually changed) - it's
        each open task's `allocated_hours` (the planned/booked hours)
        spread across its own working days (date_start -> date_deadline)
        and summed for whichever of those days fall in the selected
        period, via the same day-by-day engine the Task overload warning
        uses (hr.employee.get_daily_load). A task due next month but not
        yet started still shows up here on the days it would need to be
        worked; a task that finishes Done - on time or early, however
        many hours it actually took - drops out entirely and frees up
        the rest of its window immediately."""
        employee_ids = filters.get('employee_ids') or []
        emp_domain = [('user_id', '!=', False)]
        if employee_ids:
            emp_domain.append(('id', 'in', employee_ids))
        employees = self.env['hr.employee'].search(emp_domain)
        segments = self._period_segments_from_today(filters)
        if not segments:
            return []
        span_start = min(start for start, _end in segments)
        span_end = max(end for _start, end in segments)

        capacity = []
        for emp in employees:
            period_capacity = sum(emp.get_period_capacity_hours(start, end) for start, end in segments)
            # Simulated as ONE continuous span (not per-segment) even
            # though only the selected months are summed below - the
            # priority queue is stateful (unlike the old even-spread
            # model), so splitting it into disjoint per-segment calls
            # would forget everything scheduled in a skipped month
            # (e.g. Aug + Nov selected, Sep/Oct skipped) and wrongly dump
            # that work as fresh backlog at the start of the next segment.
            all_days = emp.get_daily_load(span_start, span_end)
            committed = sum(
                day['load'] for day in all_days
                if any(start <= day['date'] <= end for start, end in segments)
            )
            if not period_capacity and not committed:
                continue
            if period_capacity:
                free_pct = round((period_capacity - committed) / period_capacity * 100, 1)
            else:
                free_pct = -100.0 if committed else 0.0
            capacity.append({
                'id': emp.id,
                'name': emp.name,
                'allocated': round(period_capacity, 1),
                'spent': round(committed, 1),
                'free_hours': round(period_capacity - committed, 1),
                'free_pct': free_pct,
            })
        capacity.sort(key=lambda r: r['free_pct'], reverse=True)
        return capacity

    def _workload_gantt(self, filters):
        """Day-by-day load vs. capacity per employee for the selected
        period (same forward-looking window as Capacity - see
        _period_segments_from_today), for the Workload Gantt panel: a
        visual "who's overloaded and exactly when" view, one row per
        employee, one column per working day, backed by the same
        hr.employee.get_daily_load engine as everything else here."""
        employee_ids = filters.get('employee_ids') or []
        emp_domain = [('user_id', '!=', False)]
        if employee_ids:
            emp_domain.append(('id', 'in', employee_ids))
        employees = self.env['hr.employee'].search(emp_domain)
        segments = self._period_segments_from_today(filters)
        if not segments:
            return []
        span_start = min(start for start, _end in segments)
        span_end = max(end for _start, end in segments)

        rows = []
        for emp in employees:
            # One continuous simulation across the whole span, then keep
            # only the days inside the selected segments - see the same
            # note in _capacity_by_employee for why per-segment calls
            # would corrupt the priority queue's state across a gap
            # (e.g. Aug + Nov selected, Sep/Oct skipped).
            all_days = emp.get_daily_load(span_start, span_end)
            days = [
                day for day in all_days
                if any(start <= day['date'] <= end for start, end in segments)
            ]
            if not days:
                continue
            rows.append({
                'id': emp.id,
                'name': emp.name,
                'days': [{
                    'date': day['date'].isoformat(),
                    'load': day['load'],
                    'capacity': day['capacity'],
                    'overloaded': day['overloaded'],
                } for day in days],
            })
        return rows

    def _task_timeline(self, filters, window_start, window_end):
        """Individual open tasks as (start, end) bars, one per task, for the
        drag & drop Task Timeline panel (Frappe Gantt, MIT-licensed,
        vendored locally under static/lib - this Odoo install is
        Community, the native Gantt view is Enterprise-only).

        Dates are the task's *real*, unclamped date_start/date_deadline -
        `window_start`/`window_end` only decide which tasks to include
        (must overlap the window), not to clip the bar itself, because
        dragging a bar has to write back the task's actual dates and a
        clipped starting position would silently shift them on the first
        drag. Unlike Capacity/Workload Gantt this window is caller-chosen
        and NOT clamped to today - the Timeline is also meant to show
        recently-past work (e.g. its default "previous/current/next
        month"), not just what's still ahead.
        """
        employee_ids = filters.get('employee_ids') or []
        emp_domain = [('user_id', '!=', False)]
        if employee_ids:
            emp_domain.append(('id', 'in', employee_ids))
        employees = self.env['hr.employee'].search(emp_domain)
        if not employees:
            return []

        today = fields.Date.context_today(self)
        emp_by_user = {emp.user_id.id: emp for emp in employees}

        tasks = self.env['project.task'].search([
            ('user_ids', 'in', employees.user_id.ids),
            ('state', 'not in', list(DONE_TASK_STATES)),
            ('date_deadline', '!=', False),
        ])

        bars = []
        task_by_id = {}
        for task in tasks:
            deadline = fields.Date.to_date(task.date_deadline)
            start = fields.Date.to_date(task.date_start) or deadline
            if start > deadline:
                start = deadline
            if deadline < window_start or start > window_end:
                continue
            assignee = next((emp_by_user[u.id] for u in task.user_ids if u.id in emp_by_user), None)
            if not assignee:
                continue
            task_by_id[task.id] = task
            bars.append({
                'id': task.id,
                'name': task.name,
                'project': task.project_id.name or '',
                'employee': assignee.name,
                'employee_id': assignee.id,
                'start': start.isoformat(),
                'end': deadline.isoformat(),
                'allocated_hours': task.allocated_hours,
                'progress': round(task.progress or 0.0),
                'overdue': deadline < today,
            })

        # Overload detail per bar: did THIS task actually finish (all its
        # allocated_hours scheduled) by its own deadline once queued
        # against the assignee's other open tasks by priority - not "does
        # its window contain a red day" (a red day can be pure debt from a
        # different, unrelated overdue task - see hr.employee's
        # _simulate_schedule docstring). If overloaded, also surface how
        # many hours never got scheduled in time and the nearest deadline
        # that would clear it - the exact numbers a manager needs to
        # decide how to fix it, not just that something's wrong. Batched
        # one get_task_overload call per employee (spanning all of their
        # bars) instead of one per task, since it re-queries that
        # employee's whole open-task list internally.
        emp_by_id = {emp.id: emp for emp in employees}
        bars_by_employee = {}
        for bar in bars:
            bars_by_employee.setdefault(bar['employee_id'], []).append(bar)
        for emp_id, emp_bars in bars_by_employee.items():
            emp = emp_by_id[emp_id]
            span_start = min(date.fromisoformat(b['start']) for b in emp_bars)
            span_end = max(date.fromisoformat(b['end']) for b in emp_bars)
            task_overload = emp.get_task_overload(span_start, span_end)
            for bar in emp_bars:
                info = task_overload.get(bar['id'])
                bar['overloaded'] = bool(info and info['overloaded'])
                bar['excess_hours'] = info['unfinished_hours'] if info else 0.0
                bar['suggested_deadline'] = None
                if bar['overloaded']:
                    task = task_by_id[bar['id']]
                    suggested = emp.suggest_deadline_without_overload(
                        task.allocated_hours, task.date_start,
                        after_date=task.date_deadline, exclude_task_id=task.id,
                        priority=_priority_value(task.priority))
                    bar['suggested_deadline'] = suggested.isoformat() if suggested else None

        bars.sort(key=lambda b: (b['employee'], b['start']))
        return bars

    @api.model
    def get_task_timeline(self, filters=None, range_start=None, range_end=None):
        """Task Timeline is decoupled from the main dashboard's Year/Months
        filter on purpose - its default window is "previous/current/next
        calendar month" (a rolling 3-month view centered on today, not
        whatever Year/Months happens to be selected up top), and the panel
        has its own Day/Week/Month/range controls that call this
        separately rather than re-fetching the whole dashboard."""
        filters = filters or {}
        today = fields.Date.context_today(self)
        if range_start:
            window_start = fields.Date.to_date(range_start)
        else:
            window_start = today.replace(day=1) - relativedelta(months=1)
        if range_end:
            window_end = fields.Date.to_date(range_end)
        else:
            window_end = today.replace(day=1) + relativedelta(months=2) - relativedelta(days=1)
        return self._task_timeline(filters, window_start, window_end)

    @api.model
    def get_dashboard_data(self, filters=None):
        filters = filters or {}
        Timesheet = self.env['account.analytic.line']
        Task = self.env['project.task']
        spent_domain, planned_domain = self._build_domains(filters)

        total_spent = _num((Timesheet._read_group(spent_domain, [], ['unit_amount:sum']) or [(0.0,)])[0][0])
        total_planned = _num((Task._read_group(planned_domain, [], ['allocated_hours:sum']) or [(0.0,)])[0][0])
        utilization_pct = round(total_spent / total_planned * 100, 1) if total_planned else 0.0

        today = fields.Date.context_today(self)
        overdue_domain = planned_domain + [
            ('date_deadline', '<', today), ('state', 'not in', list(DONE_TASK_STATES))]
        overdue_tasks_count = Task.search_count(overdue_domain)

        by_task_type = []
        for key, total, count in Timesheet._read_group(
                spent_domain, ['task_type'], ['unit_amount:sum', '__count']):
            total = _num(total)
            by_task_type.append({
                'key': key or 'undefined',
                'label': TASK_TYPE_LABELS.get(key, 'Undefined'),
                'spent_hours': total,
                'task_count': count,
                'avg_hours': round(total / count, 2) if count else 0.0,
            })

        by_employee = []
        spent_by_employee = {}
        for employee, total in Timesheet._read_group(
                spent_domain, ['employee_id'], ['unit_amount:sum']):
            emp = _rec_id_name(employee)
            if emp:
                hours = _num(total)
                by_employee.append({**emp, 'spent_hours': hours})
                spent_by_employee[emp['id']] = hours
        by_employee.sort(key=lambda r: r['spent_hours'], reverse=True)

        employee_task_type_matrix = []
        for employee, task_type, total in Timesheet._read_group(
                spent_domain, ['employee_id', 'task_type'], ['unit_amount:sum']):
            emp = _rec_id_name(employee)
            if emp:
                employee_task_type_matrix.append({
                    'employee': emp['name'],
                    'task_type': TASK_TYPE_LABELS.get(task_type, 'Undefined'),
                    'hours': _num(total),
                })

        by_month = [
            {'month': _month_label(month), 'spent_hours': _num(total)}
            for month, total in Timesheet._read_group(
                spent_domain, ['date:month'], ['unit_amount:sum'], order='date:month asc')
        ]

        by_month_task_type = [
            {'month': _month_label(month), 'task_type': TASK_TYPE_LABELS.get(task_type, 'Undefined'), 'hours': _num(total)}
            for month, task_type, total in Timesheet._read_group(
                spent_domain, ['date:month', 'task_type'], ['unit_amount:sum'], order='date:month asc')
        ]

        spent_by_project = {
            project.id: _num(total)
            for project, total in Timesheet._read_group(
                spent_domain, ['project_id'], ['unit_amount:sum'])
            if project
        }
        planned_by_project = {
            project.id: _num(total)
            for project, total in Task._read_group(
                planned_domain, ['project_id'], ['allocated_hours:sum'])
            if project
        }
        project_names = {
            p['id']: p['name'] for p in self.env['project.project'].browse(
                set(spent_by_project) | set(planned_by_project)).read(['name'])
        }
        planned_vs_actual_by_project = [{
            'id': pid,
            'name': project_names.get(pid, ''),
            'planned': planned_by_project.get(pid, 0.0),
            'spent': spent_by_project.get(pid, 0.0),
            'over_budget': spent_by_project.get(pid, 0.0) > planned_by_project.get(pid, 0.0),
        } for pid in (set(spent_by_project) | set(planned_by_project))]
        planned_vs_actual_by_project.sort(key=lambda r: r['spent'], reverse=True)

        top_projects = [
            {**_rec_id_name(project), 'spent_hours': _num(total)}
            for project, total in Timesheet._read_group(
                spent_domain, ['project_id'], ['unit_amount:sum'],
                order='unit_amount:sum desc', limit=10)
            if project
        ]

        overdue_by_project = [
            {**_rec_id_name(project), 'overdue_count': count}
            for project, count in Task._read_group(overdue_domain, ['project_id'], ['__count'])
            if project
        ]
        overdue_by_employee = [
            {**_rec_id_name(user), 'overdue_count': count}
            for user, count in Task._read_group(overdue_domain, ['user_ids'], ['__count'])
            if user
        ]

        capacity_by_employee = self._capacity_by_employee(filters)
        workload_gantt = self._workload_gantt(filters)

        return {
            'kpi': {
                'total_planned': round(total_planned, 1),
                'total_spent': round(total_spent, 1),
                'utilization_pct': utilization_pct,
                'remaining_hours': round(total_planned - total_spent, 1),
                'overdue_tasks_count': overdue_tasks_count,
            },
            'by_task_type': by_task_type,
            'by_employee': by_employee,
            'employee_task_type_matrix': employee_task_type_matrix,
            'by_month': by_month,
            'by_month_task_type': by_month_task_type,
            'planned_vs_actual_by_project': planned_vs_actual_by_project,
            'top_projects': top_projects,
            'overdue_by_project': overdue_by_project,
            'overdue_by_employee': overdue_by_employee,
            'capacity_by_employee': capacity_by_employee,
            'workload_gantt': workload_gantt,
        }

    @api.model
    def get_timesheet_lines(self, filters=None, drill=None, limit=200):
        """Detail rows backing the drill-down table: the current global
        filters narrowed further by whatever the user just clicked on the
        main chart (a single employee, task type, or month)."""
        filters = filters or {}
        drill = drill or {}
        Timesheet = self.env['account.analytic.line']
        spent_domain, _ = self._build_domains(filters)

        if drill.get('employee_id'):
            spent_domain = Domain.AND([spent_domain, [('employee_id', '=', drill['employee_id'])]])
        if drill.get('task_type'):
            spent_domain = Domain.AND([spent_domain, [('task_type', '=', drill['task_type'])]])
        if drill.get('month'):
            year = drill.get('year') or (filters.get('years') or [fields.Date.context_today(self).year])[0]
            start, end = _month_bounds(year, drill['month'])
            spent_domain = Domain.AND(
                [spent_domain, [('date', '>=', start.isoformat()), ('date', '<=', end.isoformat())]])

        lines = Timesheet.search_read(
            spent_domain,
            ['date', 'project_id', 'employee_id', 'task_type', 'task_id', 'unit_amount'],
            order='date desc', limit=limit)
        return [{
            'date': line['date'],
            'project': line['project_id'][1] if line['project_id'] else '',
            'employee': line['employee_id'][1] if line['employee_id'] else '',
            'task_type': TASK_TYPE_LABELS.get(line['task_type'], 'Undefined'),
            'task': line['task_id'][1] if line['task_id'] else '',
            'hours': line['unit_amount'],
        } for line in lines]
