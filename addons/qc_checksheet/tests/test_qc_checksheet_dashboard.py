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

    def _data(self, **filters):
        return self.Sheet.dashboard_data(filters)

    def _row(self, data, job):
        return next(row for row in data['rows'] if row['id'] == job.id)

    def _job(self, name):
        return self._create_job(name, model=self.env['equipment.model'].create({'name': f'M-{name}'}))

    def test_cells_show_what_exists(self):
        job = self._job('J-DASH-1')
        released = self._release(self._create_checksheet(job=job))
        data = self._data(search='J-DASH-1')
        row = self._row(data, job)
        cell = row['cells'][self.type_general.id]
        self.assertEqual((cell['id'], cell['state'], cell['revision']), (released.id, 'released', 0))
        self.assertIs(cell['next'], False)
        self.assertEqual(row['released'], 1)
        self.assertEqual(data['required'], 1)
        self.assertFalse(data['can_author'])

    def test_missing_and_optional_cells(self):
        job = self._job('J-DASH-2')
        self._create_checksheet(self.type_panel, job=job)
        data = self._data(search='J-DASH-2')
        row = self._row(data, job)
        self.assertEqual(row['cells'][self.type_general.id], {'state': 'missing'})
        self.assertEqual(row['cells'][self.type_panel.id]['state'], 'draft')
        self.assertEqual([c['id'] for c in data['columns']], [self.type_general.id, self.type_panel.id])

    def test_optional_type_column_only_once_used(self):
        self._job('J-DASH-3')
        data = self._data(search='J-DASH-3')
        self.assertEqual([c['id'] for c in data['columns']], [self.type_general.id])

    def test_revision_in_progress_is_shown_with_the_one_in_use(self):
        job = self._job('J-DASH-4')
        rev0 = self._create_checksheet(job=job)
        self._create_content(rev0)
        rev0.action_submit()
        rev0.action_approve()
        rev1 = rev0.browse(rev0.action_create_revision('Change')['res_id'])
        cell = self._row(self._data(search='J-DASH-4'), job)['cells'][self.type_general.id]
        self.assertEqual(cell['id'], rev0.id)
        self.assertEqual(cell['next'], {'id': rev1.id, 'revision': 1, 'state': 'draft'})
        self.assertEqual(cell['reason'], 'Change')

    def test_waiting_days_and_overdue_setting(self):
        job = self._job('J-DASH-5')
        sheet = self._create_checksheet(job=job)
        self._create_content(sheet)
        sheet.action_submit()
        self.assertTrue(sheet.submitted_date)
        sheet.submitted_date = fields.Datetime.now() - timedelta(days=4)
        data = self._data(search='J-DASH-5')
        self.assertEqual(self._row(data, job)['cells'][self.type_general.id]['waiting_days'], 4)
        self.assertEqual(data['overdue_days'], 3)
        self.env['ir.config_parameter'].sudo().set_param('qc_checksheet.review_overdue_days', '7')
        self.assertEqual(self._data(search='J-DASH-5')['overdue_days'], 7)

    def test_kpis_and_kpi_filters(self):
        complete = self._job('J-KPI-1')
        self._release(self._create_checksheet(job=complete))
        missing = self._job('J-KPI-2')
        waiting = self._job('J-KPI-3')
        sheet = self._create_checksheet(job=waiting)
        self._create_content(sheet)
        sheet.action_submit()
        data = self._data(search='J-KPI')
        self.assertEqual(data['kpis'], {'missing': 1, 'waiting': 1, 'draft': 0, 'complete': 1})
        self.assertEqual([r['id'] for r in self._data(search='J-KPI', kpi='missing')['rows']], [missing.id])
        self.assertEqual([r['id'] for r in self._data(search='J-KPI', kpi='waiting')['rows']], [waiting.id])
        self.assertEqual([r['id'] for r in self._data(search='J-KPI', kpi='complete')['rows']], [complete.id])

    def test_only_in_progress_jobs_by_default_and_eol_on_demand(self):
        running = self._job('J-STATUS-1')
        ended = self._job('J-STATUS-2')
        ended.last_update_status = 'eol'
        self.assertFalse(ended.active)
        ids = [r['id'] for r in self._data(search='J-STATUS')['rows']]
        self.assertEqual(ids, [running.id])
        ids = [r['id'] for r in self._data(search='J-STATUS', statuses=['eol'])['rows']]
        self.assertEqual(ids, [ended.id])

    def test_search_model_filter_sort_and_pages(self):
        first = self._job('J-PAGE-01')
        second = self._job('J-PAGE-02')
        self._release(self._create_checksheet(job=first))
        data = self._data(search='J-PAGE')
        self.assertEqual([r['id'] for r in data['rows']], [second.id, first.id])
        self.assertEqual({m['id'] for m in data['models']}, {first.model_id.id, second.model_id.id})
        self.assertEqual([r['id'] for r in self._data(search='M-J-PAGE-01')['rows']], [first.id])
        self.assertEqual([r['id'] for r in self._data(search='J-PAGE', model_id=first.model_id.id)['rows']], [first.id])
        self.assertEqual([r['id'] for r in self._data(search='J-PAGE', sort='done')['rows']], [second.id, first.id])
        paged = self._data(search='J-PAGE', offset=1)
        self.assertEqual(([r['id'] for r in paged['rows']], paged['total']), ([first.id], 2))

    def test_jobs_without_a_model_are_left_out(self):
        self.env['project.project'].create({'name': 'J-NOMODEL-1'})
        self.assertEqual(self._data(search='J-NOMODEL')['rows'], [])

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
        self.assertEqual(self.Sheet.dashboard_data({})['overdue_days'], 5)

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
