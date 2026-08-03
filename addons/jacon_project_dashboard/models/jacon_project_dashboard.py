from odoo import api, fields, models
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
        return {
            'projects': [{'id': p['id'], 'name': p['name']} for p in projects],
            'employees': [{'id': e['id'], 'name': e['name']} for e in employees],
            'task_types': [{'key': key, 'label': label} for key, label in TASK_TYPE_SELECTION],
        }

    def _build_domains(self, filters):
        """Two separate domains: Spent (Timesheet, date-bounded) and Planned
        (Task, not date-bounded - `allocated_hours` is a single static
        number per task, it has no per-month breakdown to filter on)."""
        date_from = filters.get('date_from')
        date_to = filters.get('date_to')
        project_ids = filters.get('project_ids') or []
        employee_ids = filters.get('employee_ids') or []
        task_types = filters.get('task_types') or []

        spent_domain = [('project_id', '!=', False)]
        if date_from:
            spent_domain.append(('date', '>=', date_from))
        if date_to:
            spent_domain.append(('date', '<=', date_to))
        if project_ids:
            spent_domain.append(('project_id', 'in', project_ids))
        if employee_ids:
            spent_domain.append(('employee_id', 'in', employee_ids))
        if task_types:
            spent_domain.append(('task_type', 'in', task_types))

        planned_domain = [('project_id', '!=', False)]
        if project_ids:
            planned_domain.append(('project_id', 'in', project_ids))
        if employee_ids:
            user_ids = self.env['hr.employee'].browse(employee_ids).mapped('user_id').ids
            planned_domain.append(('user_ids', 'in', user_ids))
        if task_types:
            planned_domain.append(('task_type', 'in', task_types))

        return spent_domain, planned_domain

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
        for employee, total in Timesheet._read_group(
                spent_domain, ['employee_id'], ['unit_amount:sum']):
            emp = _rec_id_name(employee)
            if emp:
                by_employee.append({**emp, 'spent_hours': _num(total)})
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

        return {
            'kpi': {
                'total_planned': round(total_planned, 1),
                'total_spent': round(total_spent, 1),
                'utilization_pct': utilization_pct,
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
        }
