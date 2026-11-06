from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests.common import new_test_user, tagged

from .common import QcChecksheetCase


@tagged('post_install', '-at_install')
class TestQcChecksheetDashboard(QcChecksheetCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.viewer = new_test_user(cls.env, login='qc_dash_viewer', groups='base.group_user')
        cls.type_panel.required = False
        cls.Sheet = cls.env['qc.checksheet'].with_user(cls.viewer)

    def _data(self, domain=None):
        return self.Sheet.get_dashboard_data(domain or [])

    def _job(self, name, **vals):
        return self._create_job(name, model=self.env['equipment.model'].create({'name': f'M-{name}'}), **vals)

    def _scoped(self, job):
        return self._data([('job_number', '=', job.id)])

    def test_counts_by_status_ignore_superseded(self):
        job = self._job('J-DASH-1')
        rev0 = self._create_checksheet(job=job)
        self._create_content(rev0)
        rev0.action_submit()
        rev0.action_approve()
        rev1 = rev0.browse(rev0.action_create_revision('Change')['res_id'])
        rev1.action_submit()
        rev1.action_approve()
        rev1.browse(rev1.action_create_revision('Again')['res_id'])
        data = self._scoped(job)
        # Rev 0 is superseded; Rev 1 Released and Rev 2 Draft both count, as in the lists they open.
        self.assertEqual(data['total'], 2)
        self.assertEqual(data['kpis'], {'draft': 1, 'review': 0, 'overdue': 0, 'released': 1})
        self.assertEqual([(i['key'], i['count']) for i in data['by_state']], [('draft', 1), ('released', 1)])
        self.assertEqual([(i['key'], i['count']) for i in data['by_type']], [(self.type_general.id, 2)])
        self.assertEqual(data['by_model'], [{'key': 'M-J-DASH-1', 'label': 'M-J-DASH-1', 'count': 2}])
        self.assertEqual(data['by_job'], [{'key': job.id, 'label': 'J-DASH-1', 'count': 2}])
        self.assertEqual([r['id'] for r in data['released']], [rev1.id])

    def test_waiting_too_long_follows_the_setting(self):
        job = self._job('J-DASH-2')
        sheet = self._create_checksheet(job=job)
        self._create_content(sheet)
        sheet.action_submit()
        self.assertTrue(sheet.submitted_date)
        sheet.submitted_date = fields.Datetime.now() - timedelta(days=4)
        data = self._scoped(job)
        self.assertEqual((data['kpis']['review'], data['kpis']['overdue'], data['overdue_days']), (1, 1, 3))
        self.assertEqual(data['waiting'][0]['waiting_days'], 4)
        self.env['ir.config_parameter'].sudo().set_param('qc_checksheet.review_overdue_days', '7')
        data = self._scoped(job)
        self.assertEqual((data['kpis']['overdue'], data['overdue_days']), (0, 7))

    def test_job_status_is_searchable_for_archived_jobs(self):
        running = self._job('J-DASH-3')
        ended = self._job('J-DASH-4')
        self._create_checksheet(job=running)
        sheet = self._create_checksheet(job=ended)
        ended.last_update_status = 'eol'
        self.assertFalse(ended.active)
        self.assertEqual(sheet.job_status, 'eol')
        open_jobs = [('job_status', 'in', ['in_progress', 'on_hold'])]
        domain = open_jobs + [('job_number', 'in', [running.id, ended.id])]
        self.assertEqual(self._data(domain)['total'], 1)
        domain = [('job_status', '=', 'eol'), ('job_number', 'in', [running.id, ended.id])]
        self.assertEqual(self._data(domain)['total'], 1)

    def test_a_job_the_user_cannot_read_still_shows_by_name(self):
        job = self._job('J-DASH-PRIVATE', privacy_visibility='followers')
        sheet = self._create_checksheet(job=job)
        self._create_content(sheet)
        sheet.action_submit()
        data = self._data([('job_number', '=', job.id)])
        self.assertEqual([row['job'] for row in data['waiting']], ['J-DASH-PRIVATE'])
        self.assertEqual([item['label'] for item in data['by_job']], ['J-DASH-PRIVATE'])

    OPEN_JOBS = [('job_status', 'in', ['in_progress', 'on_hold'])]

    def _coverage_jobs(self):
        complete = self._job('J-COV-1')
        self._release(self._create_checksheet(job=complete))
        missing = self._job('J-COV-2')
        paused = self._job('J-COV-3')
        paused.last_update_status = 'on_hold'
        closed = self._job('J-COV-4')
        closed.last_update_status = 'cancelled'
        self.env['project.project'].create({'name': 'J-COV-NOMODEL'})
        return complete, missing, paused, closed

    def _missing_ids(self, domain):
        action = self.Sheet.action_open_missing_jobs(domain)
        return set(self.env['project.project'].with_context(active_test=False).search(action['domain']).ids)

    def test_jobs_missing_sheets_follow_the_open_jobs_filter(self):
        before = self._data(self.OPEN_JOBS)['jobs']
        complete, missing, paused, closed = self._coverage_jobs()
        jobs = self._data(self.OPEN_JOBS)['jobs']
        self.assertEqual(jobs['total'] - before['total'], 3)
        self.assertEqual(jobs['missing'] - before['missing'], 2)
        self.assertEqual(jobs['complete'] - before['complete'], 1)
        ids = self._missing_ids(self.OPEN_JOBS)
        self.assertTrue({missing.id, paused.id} <= ids)
        self.assertFalse({closed.id, complete.id} & ids)
        # Without the filter, closed Jobs count too.
        self.assertIn(closed.id, self._missing_ids([]))

    def test_jobs_follow_the_job_conditions_of_the_search(self):
        complete, missing, _paused, _closed = self._coverage_jobs()
        by_model = [('machine_model', 'ilike', 'M-J-COV-2')]
        self.assertEqual(self._data(by_model)['jobs'], {'total': 1, 'missing': 1, 'complete': 0})
        self.assertEqual(self._missing_ids(by_model), {missing.id})
        by_job = [('job_number', 'ilike', 'J-COV-1')]
        self.assertEqual(self._data(by_job)['jobs'], {'total': 1, 'missing': 0, 'complete': 1})
        self.assertEqual(self._data([('job_number', '=', complete.id)])['jobs']['total'], 1)
        # Conditions on the sheet itself say nothing about Jobs with no sheet.
        domain = by_model + [('state', '=', 'released')]
        self.assertEqual(self._data(domain)['jobs'], {'total': 1, 'missing': 1, 'complete': 0})

    def test_job_info_for_the_new_page(self):
        job = self._job('J-INFO-1')
        self.assertEqual(self.Sheet.editor_job_info(job.id), {'id': job.id, 'name': 'J-INFO-1', 'model': 'M-J-INFO-1'})

    def test_job_info_of_a_deleted_job_is_false(self):
        # jacon_core won't let a test delete a Job, so take an id no Job has.
        missing_id = self._job('J-INFO-2').id + 1000
        self.assertIs(self.Sheet.editor_job_info(missing_id), False)

    # Settings

    def test_settings_show_and_save_the_overdue_days(self):
        admin = new_test_user(
            self.env, login='qc_dash_admin', groups='base.group_user,qc_checksheet.group_qc_admin')
        settings = self.env['qc.checksheet.settings'].with_user(admin).create({})
        self.assertEqual(settings.review_overdue_days, 3)
        settings.review_overdue_days = 5
        settings.action_save()
        self.assertEqual(self.Sheet.get_dashboard_data([])['overdue_days'], 5)

    def test_settings_refuse_zero_days(self):
        admin = new_test_user(
            self.env, login='qc_dash_admin2', groups='base.group_user,qc_checksheet.group_qc_admin')
        settings = self.env['qc.checksheet.settings'].with_user(admin).create({'review_overdue_days': 0})
        with self.assertRaises(UserError):
            settings.action_save()

    def test_only_a_qc_administrator_changes_settings(self):
        author = new_test_user(
            self.env, login='qc_dash_author', groups='base.group_user,qc_checksheet.group_qc_author')
        with self.assertRaises(AccessError):
            self.env['qc.checksheet.settings'].with_user(author).create({'review_overdue_days': 9})
