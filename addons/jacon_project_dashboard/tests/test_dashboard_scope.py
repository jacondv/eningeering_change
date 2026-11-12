from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestDashboardScope(TransactionCase):
    """Who sees what on the Hours Dashboard: a user only their own, an Administrator everyone's, and the
    "My to-do" reminders, always of the person looking."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Employee = cls.env['hr.employee']
        cls.user_a = new_test_user(
            cls.env, login='dash_a', groups='base.group_user,jacon_project_dashboard.group_project_dashboard_user')
        cls.user_b = new_test_user(
            cls.env, login='dash_b', groups='base.group_user,jacon_project_dashboard.group_project_dashboard_user')
        cls.admin = new_test_user(
            cls.env, login='dash_admin', groups='base.group_user,jacon_project_dashboard.group_project_dashboard_admin')
        cls.nobody = new_test_user(cls.env, login='dash_nobody', groups='base.group_user')
        cls.emp_a = Employee.create({'name': 'Dash A', 'user_id': cls.user_a.id})
        cls.emp_b = Employee.create({'name': 'Dash B', 'user_id': cls.user_b.id})
        cls.emp_admin = Employee.create({'name': 'Dash Admin', 'user_id': cls.admin.id})
        cls.project = cls.env['project.project'].create({'name': 'Dash Project'})
        cls.today = fields.Date.context_today(cls.env['project.task'])

    def _task(self, user, name, **vals):
        return self.env['project.task'].create({
            'name': name, 'project_id': self.project.id, 'user_ids': [(6, 0, user.ids)],
            'task_type': '3d', **vals})

    def _hours(self, task, employee, hours):
        return self.env['account.analytic.line'].create({
            'name': 'work', 'task_id': task.id, 'project_id': self.project.id,
            'employee_id': employee.id, 'unit_amount': hours, 'date': self.today})

    def _dashboard(self, user):
        return self.env['jacon.project.dashboard'].with_user(user)

    def _reminders(self, user, **filters):
        return self._dashboard(user).get_my_reminders(filters)

    def _counts(self, reminders):
        return {kind['key']: kind['count'] for kind in reminders['kinds']}

    # Who sees what

    def test_a_user_sees_only_their_own_hours_an_administrator_everyones(self):
        self._hours(self._task(self.user_a, 'A work'), self.emp_a, 3)
        self._hours(self._task(self.user_b, 'B work'), self.emp_b, 5)
        filters = {'years': [self.today.year], 'project_ids': [self.project.id]}
        mine = self._dashboard(self.user_a).get_dashboard_data(filters)
        self.assertEqual(mine['kpi']['total_spent'], 3)
        self.assertEqual([row['name'] for row in mine['by_employee']], ['Dash A'])
        # Asking for someone else changes nothing: the server answers with the user's own.
        sneaky = self._dashboard(self.user_a).get_dashboard_data(dict(filters, employee_ids=[self.emp_b.id]))
        self.assertEqual(sneaky['kpi']['total_spent'], 3)
        everyone = self._dashboard(self.admin).get_dashboard_data(filters)
        self.assertEqual(everyone['kpi']['total_spent'], 8)
        only_b = self._dashboard(self.admin).get_dashboard_data(dict(filters, employee_ids=[self.emp_b.id]))
        self.assertEqual(only_b['kpi']['total_spent'], 5)

    def test_someone_without_an_employee_sees_nothing(self):
        emp = self.env['hr.employee'].create({'name': 'No Login'})
        self.assertFalse(emp.user_id)
        user = new_test_user(
            self.env, login='dash_noemp', groups='base.group_user,jacon_project_dashboard.group_project_dashboard_user')
        self._hours(self._task(self.user_a, 'A work'), self.emp_a, 3)
        data = self._dashboard(user).get_dashboard_data({'years': [self.today.year]})
        self.assertEqual(data['kpi']['total_spent'], 0)
        self.assertEqual(data['by_employee'], [])

    def test_the_filter_options_follow_the_role(self):
        self._hours(self._task(self.user_a, 'A work'), self.emp_a, 1)
        self.env['project.project'].create({'name': 'Dash Other Project'})
        as_user = self._dashboard(self.user_a).get_filter_options()
        self.assertFalse(as_user['is_admin'])
        self.assertEqual([e['name'] for e in as_user['employees']], ['Dash A'])
        self.assertEqual([p['name'] for p in as_user['projects']], ['Dash Project'])
        as_admin = self._dashboard(self.admin).get_filter_options()
        self.assertTrue(as_admin['is_admin'])
        self.assertGreaterEqual(len(as_admin['employees']), 3)
        self.assertIn('Dash Other Project', [p['name'] for p in as_admin['projects']])

    def test_without_a_dashboard_group_there_is_no_access(self):
        for method in ('get_filter_options', 'get_dashboard_data', 'get_task_timeline', 'get_my_reminders'):
            with self.assertRaises(AccessError):
                getattr(self._dashboard(self.nobody), method)()

    def test_an_administrator_is_also_a_user(self):
        self.assertTrue(self.admin.has_group('jacon_project_dashboard.group_project_dashboard_user'))

    # Reminders

    def test_reminders_are_the_viewers_own_tasks_only(self):
        self._task(self.user_a, 'A no type', task_type=False, date_deadline=self.today + timedelta(days=5))
        self._task(self.user_b, 'B no type', task_type=False, date_deadline=self.today + timedelta(days=5))
        reminders = self._reminders(self.user_a)
        self.assertEqual([row['name'] for row in reminders['rows']], ['A no type'])
        self.assertEqual(self._counts(reminders)['no_type'], 1)
        # An Administrator gets their own list too, not everyone's.
        self.assertEqual(self._reminders(self.admin)['rows'], [])

    def test_the_four_kinds(self):
        self._task(self.user_a, 'Late', date_deadline=self.today - timedelta(days=3))
        self._task(self.user_a, 'No deadline')
        self._task(self.user_a, 'No type', task_type=False, date_deadline=self.today + timedelta(days=9))
        self._task(self.user_a, 'Done, no hours', state='1_done')
        self._hours(self._task(self.user_a, 'Done, with hours', state='1_done'), self.emp_a, 2)
        self._task(self.user_a, 'Fine', date_deadline=self.today + timedelta(days=9))
        reminders = self._reminders(self.user_a, years=[self.today.year])
        self.assertEqual(self._counts(reminders), {
            'overdue': 1, 'done_no_timesheet': 1, 'no_deadline': 1, 'no_type': 1})
        issues = {row['name']: row['issues'] for row in reminders['rows']}
        self.assertEqual(issues, {
            'Late': ['overdue'], 'No deadline': ['no_deadline'], 'No type': ['no_type'],
            'Done, no hours': ['done_no_timesheet']})

    def test_a_task_with_two_problems_is_one_row_with_both(self):
        self._task(self.user_a, 'Both', task_type=False, date_deadline=self.today - timedelta(days=1))
        rows = self._reminders(self.user_a)['rows']
        self.assertEqual([(row['name'], row['issues']) for row in rows], [('Both', ['overdue', 'no_type'])])

    def test_a_subtask_needs_no_deadline_but_its_parent_does(self):
        parent = self._task(self.user_a, 'Parent')
        self._task(self.user_a, 'Child', parent_id=parent.id)
        rows = self._reminders(self.user_a)['rows']
        self.assertEqual([row['name'] for row in rows], ['Parent'])

    def test_the_filters_apply(self):
        other_project = self.env['project.project'].create({'name': 'Dash Second'})
        self._task(self.user_a, 'Here')
        self.env['project.task'].create({
            'name': 'There', 'project_id': other_project.id, 'user_ids': [(6, 0, self.user_a.ids)], 'task_type': '2d'})
        self.assertEqual(len(self._reminders(self.user_a)['rows']), 2)
        self.assertEqual(
            [r['name'] for r in self._reminders(self.user_a, project_ids=[other_project.id])['rows']], ['There'])
        self.assertEqual([r['name'] for r in self._reminders(self.user_a, task_types=['3d'])['rows']], ['Here'])

    def test_the_period_decides_which_done_tasks_count_but_open_ones_always_show(self):
        done = self._task(self.user_a, 'Done long ago', state='1_done')
        done.date_last_stage_update = fields.Datetime.now() - timedelta(days=400)
        self._task(self.user_a, 'Open')
        reminders = self._reminders(self.user_a, years=[self.today.year])
        self.assertEqual([r['name'] for r in reminders['rows']], ['Open'])
        reminders = self._reminders(self.user_a, years=[self.today.year - 1])
        self.assertEqual(sorted(r['name'] for r in reminders['rows']), ['Done long ago', 'Open'])

    # Task Timeline: Done tasks

    def test_done_tasks_are_on_the_timeline_only_when_asked(self):
        self._task(self.user_a, 'Still open', date_deadline=self.today + timedelta(days=2))
        self._task(self.user_a, 'Finished', state='1_done', date_deadline=self.today + timedelta(days=2))
        names = lambda **f: sorted(b['name'] for b in self._dashboard(self.user_a).get_task_timeline(f)['bars'])
        self.assertEqual(names(), ['Still open'])
        self.assertEqual(names(show_done=True), ['Finished', 'Still open'])
        bars = {b['name']: b for b in self._dashboard(self.user_a).get_task_timeline({'show_done': True})['bars']}
        self.assertTrue(bars['Finished']['done'])
        self.assertFalse(bars['Still open']['done'])

    def test_the_timeline_of_a_user_holds_only_their_own_tasks(self):
        self._task(self.user_a, 'A task', date_deadline=self.today + timedelta(days=2))
        self._task(self.user_b, 'B task', date_deadline=self.today + timedelta(days=2))
        bars = self._dashboard(self.user_a).get_task_timeline({})['bars']
        self.assertEqual([b['name'] for b in bars], ['A task'])
        everyone = self._dashboard(self.admin).get_task_timeline({})['bars']
        self.assertEqual(sorted(b['name'] for b in everyone), ['A task', 'B task'])
