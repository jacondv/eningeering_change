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

    def _scoped(self, model):
        return self._data([('model_id', '=', model.id)])

    def test_counts_by_status_ignore_superseded(self):
        model = self._create_model('M-DASH-1')
        rev0 = self._create_checksheet(model=model)
        self._create_content(rev0)
        rev0.action_submit()
        rev0.action_approve()
        rev1 = rev0.browse(rev0.action_create_revision('Change')['res_id'])
        rev1.action_submit()
        rev1.action_approve()
        rev1.browse(rev1.action_create_revision('Again')['res_id'])
        data = self._scoped(model)
        # Rev 0 is superseded; Rev 1 Released and Rev 2 Draft both count, as in the lists they open.
        self.assertEqual(data['total'], 2)
        self.assertEqual(data['kpis'], {'draft': 1, 'review': 0, 'overdue': 0, 'released': 1})
        self.assertEqual([(i['key'], i['count']) for i in data['by_state']], [('draft', 1), ('released', 1)])
        self.assertEqual([(i['key'], i['count']) for i in data['by_type']], [(self.type_general.id, 2)])
        self.assertEqual(data['by_model'], [{'key': model.id, 'label': 'M-DASH-1', 'count': 2}])
        self.assertEqual([r['id'] for r in data['released']], [rev1.id])
        self.assertEqual(data['released'][0]['model'], 'M-DASH-1')

    def test_waiting_too_long_follows_the_setting(self):
        model = self._create_model()
        sheet = self._create_checksheet(model=model)
        self._create_content(sheet)
        sheet.action_submit()
        self.assertTrue(sheet.submitted_date)
        sheet.submitted_date = fields.Datetime.now() - timedelta(days=4)
        data = self._scoped(model)
        self.assertEqual((data['kpis']['review'], data['kpis']['overdue'], data['overdue_days']), (1, 1, 3))
        self.assertEqual(data['waiting'][0]['waiting_days'], 4)
        self.env['ir.config_parameter'].sudo().set_param('qc_checksheet.review_overdue_days', '7')
        data = self._scoped(model)
        self.assertEqual((data['kpis']['overdue'], data['overdue_days']), (0, 7))

    # Jobs waiting for sheets

    def _coverage_jobs(self):
        """Open Jobs of a covered and an uncovered Model, a paused and a closed one."""
        covered = self._create_model('M-COV-OK')
        self._release(self._create_checksheet(model=covered))
        uncovered = self._create_model('M-COV-NO')
        complete = self._create_job('J-COV-1', model=covered)
        missing = self._create_job('J-COV-2', model=uncovered)
        paused = self._create_job('J-COV-3', model=uncovered)
        paused.last_update_status = 'on_hold'
        closed = self._create_job('J-COV-4', model=uncovered)
        closed.last_update_status = 'cancelled'
        self.env['project.project'].create({'name': 'J-COV-NOMODEL'})
        return complete, missing, paused, closed

    def _waiting_ids(self, domain):
        action = self.Sheet.action_open_waiting_jobs(domain)
        return set(self.env['project.project'].with_context(active_test=False).search(action['domain']).ids)

    def test_jobs_waiting_for_sheets_are_open_jobs_their_model_cannot_serve(self):
        before = self._data()['waiting_jobs']
        complete, missing, paused, closed = self._coverage_jobs()
        self.assertEqual(self._data()['waiting_jobs'] - before, 2)
        ids = self._waiting_ids([])
        self.assertTrue({missing.id, paused.id} <= ids)
        self.assertFalse({closed.id, complete.id} & ids)

    def test_a_job_that_printed_is_no_longer_waiting(self):
        _complete, missing, _paused, _closed = self._coverage_jobs()
        sheet = self._release(self._create_checksheet(model=missing.model_id))
        self.env['qc.job.checksheet'].job_print(missing.id, [self.type_general.id])
        # Even with nothing Released on the Model any more, the printed Revision serves it.
        sheet.write({'state': 'superseded'})
        self.assertNotIn(missing.id, self._waiting_ids([]))

    def test_waiting_jobs_follow_the_model_conditions_of_the_search(self):
        _complete, missing, paused, _closed = self._coverage_jobs()
        by_model = [('machine_model', 'ilike', 'M-COV-NO')]
        self.assertEqual(self._data(by_model)['waiting_jobs'], 2)
        self.assertEqual(self._waiting_ids(by_model), {missing.id, paused.id})
        self.assertEqual(self._data([('model_id', 'ilike', 'M-COV-OK')])['waiting_jobs'], 0)
        self.assertEqual(self._data([('model_id', '=', missing.model_id.id)])['waiting_jobs'], 2)
        # Conditions on the sheet itself say nothing about Jobs with no sheet.
        self.assertEqual(self._data(by_model + [('state', '=', 'released')])['waiting_jobs'], 2)

    # By Job Number

    def _printed_jobs(self, count, model=None):
        model = model or self._create_model()
        self._release(self._create_checksheet(model=model))
        jobs = self.env['project.project']
        for index in range(count):
            job = self._create_job(f'J-BYJOB-{index:02d}', model=model)
            self.env['qc.job.checksheet'].job_print(job.id, [self.type_general.id])
            jobs |= job
        return model, jobs

    def test_jobs_are_paged_and_follow_the_search(self):
        model, jobs = self._printed_jobs(23)
        scoped = [('model_id', '=', model.id)]
        first = self.Sheet.dashboard_jobs(scoped)
        self.assertEqual((first['total'], first['page'], len(first['items'])), (23, 0, 10))
        # Newest Job number first, and each Job counts the sheets it printed.
        self.assertEqual(first['items'][0], {'key': jobs[-1].id, 'label': 'J-BYJOB-22', 'count': 1})
        last = self.Sheet.dashboard_jobs(scoped, 2)
        self.assertEqual((last['page'], len(last['items'])), (2, 3))
        self.assertEqual(last['items'][-1]['label'], 'J-BYJOB-00')
        # A page past the end falls back to the last one.
        self.assertEqual(self.Sheet.dashboard_jobs(scoped, 9)['page'], 2)
        # The panel's own box narrows the Jobs, and a search bar condition the sheets.
        found = self.Sheet.dashboard_jobs(scoped, 1, 'byjob-1')
        self.assertEqual((found['total'], found['page']), (10, 0))
        self.assertEqual(self.Sheet.dashboard_jobs([('model_id', '=', model.id), ('state', '=', 'draft')])['total'], 0)

    def test_jobs_still_on_a_superseded_revision_are_listed(self):
        model, jobs = self._printed_jobs(1)
        sheet = jobs.qc_job_checksheet_ids.checksheet_id
        sheet.write({'state': 'superseded'})
        self.assertEqual(self.Sheet.dashboard_jobs([('model_id', '=', model.id)])['total'], 1)

    def test_a_job_the_user_cannot_read_still_shows_by_name(self):
        model, _jobs = self._printed_jobs(0)
        private = self._create_job('J-BYJOB-PRIVATE', model=model, privacy_visibility='followers')
        self.env['qc.job.checksheet'].job_print(private.id, [self.type_general.id])
        items = self.Sheet.dashboard_jobs([('model_id', '=', model.id)])['items']
        self.assertEqual([item['label'] for item in items], ['J-BYJOB-PRIVATE'])

    # Revision changes waiting

    def _pending_change(self, model, job_name, days_ago=0):
        """A Job of `model` pinned to Rev 0, a Rev 1 released, and a request to move to it."""
        approver = new_test_user(
            self.env, login=f'qc_dash_appr_{job_name}', groups='base.group_user,qc_checksheet.group_qc_approver')
        rev0 = self._create_checksheet(model=model)
        self._create_content(rev0)
        rev0.action_submit()
        rev0.action_approve()
        job = self._create_job(job_name, model=model)
        job_sheet = self.env['qc.job.checksheet'].browse(
            self.env['qc.job.checksheet'].job_print(job.id, [self.type_general.id]))
        rev1 = rev0.browse(rev0.action_create_revision('Change')['res_id'])
        rev1.action_submit()
        rev1.action_approve()
        request = self.env['qc.job.checksheet.change'].browse(job_sheet.action_request_change('Please'))
        request.sudo().requested_date = fields.Datetime.now() - timedelta(days=days_ago)
        return request, approver

    def test_changes_waiting_are_counted_and_listed_oldest_first(self):
        before = self._data()['rev_changes']['total']
        newer, _ = self._pending_change(self._create_model('M-CHG-1'), 'J-CHG-1', days_ago=1)
        older, _ = self._pending_change(self._create_model('M-CHG-2'), 'J-CHG-2', days_ago=6)
        data = self._data()['rev_changes']
        self.assertEqual(data['total'] - before, 2)
        ids = [item['id'] for item in data['items']]
        self.assertLess(ids.index(older.id), ids.index(newer.id))
        row = next(item for item in data['items'] if item['id'] == older.id)
        self.assertEqual((row['job'], row['from_revision'], row['to_revision'], row['waiting_days']), ('J-CHG-2', 0, 1, 6))
        self.assertEqual(row['job_id'], older.job_id.id)
        self.assertTrue(row['requested_by'])
        self.assertEqual(row['type'], self.type_general.name)

    def test_decided_changes_leave_the_dashboard(self):
        request, approver = self._pending_change(self._create_model('M-CHG-3'), 'J-CHG-3')
        scoped = [('model_id', '=', request.from_checksheet_id.model_id.id)]
        self.assertEqual(self._data(scoped)['rev_changes']['total'], 1)
        request.with_user(approver).action_approve()
        self.assertEqual(self._data(scoped)['rev_changes']['total'], 0)

    def test_changes_follow_the_search_bar_even_for_a_superseded_revision(self):
        request, _ = self._pending_change(self._create_model('M-CHG-4'), 'J-CHG-4')
        self._pending_change(self._create_model('M-CHG-5'), 'J-CHG-5')
        # The Job still prints Rev 0, Superseded since Rev 1 was released: the sheet lists leave it out.
        self.assertEqual(request.from_checksheet_id.state, 'superseded')
        by_model = [('model_id', '=', request.from_checksheet_id.model_id.id)]
        self.assertEqual([i['id'] for i in self._data(by_model)['rev_changes']['items']], [request.id])
        self.assertEqual(self._data([('model_id', '=', 0)])['rev_changes']['total'], 0)
        self.assertEqual(self._data(by_model)['total'], 1)

    def test_model_info_for_the_new_page(self):
        model = self._create_model('M-INFO-1')
        self.assertEqual(self.Sheet.editor_model_info(model.id), {'id': model.id, 'name': 'M-INFO-1', 'model': ''})
        self.assertIs(self.Sheet.editor_model_info(model.id + 1000), False)

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
