from datetime import timedelta

from psycopg2 import IntegrityError

from odoo import fields

from odoo.exceptions import AccessError, UserError
from odoo.tests.common import new_test_user, tagged
from odoo.tools import mute_logger

from .common import QcChecksheetCase


@tagged('post_install', '-at_install')
class TestQcJobChecksheet(QcChecksheetCase):
    """A Job prints its Model's sheets, keeping the Revision it first printed."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.author = new_test_user(
            cls.env, login='qc_job_author', groups='base.group_user,qc_checksheet.group_qc_author')
        cls.approver = new_test_user(
            cls.env, login='qc_job_approver', groups='base.group_user,qc_checksheet.group_qc_approver')
        cls.viewer = new_test_user(cls.env, login='qc_job_viewer', groups='base.group_user')
        cls.type_hydraulic = cls.env['qc.checksheet.type'].create({'name': 'Hydraulic', 'code': 'HY'})
        cls.type_panel.required = False
        cls.JobSheet = cls.env['qc.job.checksheet'].with_user(cls.viewer)

    def _released(self, checksheet_type=None, model=None):
        sheet = self._create_checksheet(checksheet_type, model=model or self.model_za90).with_user(self.author)
        self._create_content(sheet)
        sheet.action_submit()
        sheet.with_user(self.approver).action_approve()
        return sheet

    def _new_revision(self, sheet):
        """The next Revision of `sheet`, approved, so it becomes the Model's current one."""
        rev = sheet.browse(sheet.with_user(self.author).action_create_revision('Change')['res_id'])
        rev.with_user(self.author).action_submit()
        rev.with_user(self.approver).action_approve()
        return rev

    def _row(self, overview, checksheet_type):
        return next(row for row in overview['rows'] if row['type_id'] == checksheet_type.id)

    def _print(self, job, *types):
        return self.JobSheet.browse(self.JobSheet.job_print(job.id, [t.id for t in types]))

    # Pinning

    def test_first_print_pins_the_current_revision(self):
        rev0 = self._released()
        job = self._create_job()
        job_sheet = self._print(job, self.type_general)
        self.assertEqual(job_sheet.checksheet_id, rev0)
        self.assertEqual(job_sheet.pinned_by_id, self.viewer)
        self.assertTrue(job_sheet.pinned_date)
        # Printing again reuses it.
        self.assertEqual(self._print(job, self.type_general), job_sheet)

    def test_every_way_of_pinning_leaves_the_same_trace(self):
        rev0 = self._released()
        printed = self._print(self._create_job(), self.type_general)
        self.assertEqual((printed.pinned_by_id, bool(printed.pinned_date)), (self.viewer, True))
        self.assertIn('first print', printed.message_ids[0].body)
        chosen = self.JobSheet.browse(self.JobSheet.job_pin(
            self._create_job().id, self.type_general.id, rev0.id, 'Built to Rev 0'))
        self.assertEqual((chosen.pinned_by_id, bool(chosen.pinned_date)), (self.viewer, True))
        self.assertIn('Built to Rev 0', chosen.message_ids[0].body)

    def test_a_new_revision_does_not_touch_a_job_that_already_printed(self):
        rev0 = self._released()
        old_job = self._create_job()
        old_sheet = self._print(old_job, self.type_general)
        rev1 = self._new_revision(rev0)

        self.assertEqual(rev0.state, 'superseded')
        self.assertEqual(self._print(old_job, self.type_general).checksheet_id, rev0)
        self.assertTrue(old_sheet.update_available)
        # A Job printing for the first time gets the new one.
        self.assertEqual(self._print(self._create_job(), self.type_general).checksheet_id, rev1)

    # Changing the Revision of a Job: asked for, then approved

    def _request(self, job_sheet, reason='Needs it', revision=None):
        return self.env['qc.job.checksheet.change'].browse(
            job_sheet.with_user(self.viewer).action_request_change(reason, revision and revision.id))

    def test_a_change_waits_for_approval_and_changes_nothing_before(self):
        rev0 = self._released()
        job_sheet = self._print(self._create_job(), self.type_general)
        rev1 = self._new_revision(rev0)
        with self.assertRaisesRegex(UserError, 'reason'):
            job_sheet.action_request_change(' ')
        request = self._request(job_sheet, 'EC-1 applies to this machine')
        self.assertEqual((request.state, request.from_revision, request.to_revision), ('pending', 1, 2))
        self.assertEqual(request.requested_by_id, self.viewer)
        # The Job still prints Rev 0.
        self.assertEqual(job_sheet.checksheet_id, rev0)
        # The Approvers are told, and only one request can wait at a time.
        self.assertTrue(request.sudo().activity_ids.filtered(lambda a: a.user_id == self.approver))
        with self.assertRaisesRegex(UserError, 'already waiting'):
            self._request(job_sheet)
        request.with_user(self.approver).action_approve()
        self.assertEqual(request.state, 'approved')
        self.assertEqual((request.decided_by_id, bool(request.decided_date)), (self.approver, True))
        self.assertEqual(job_sheet.checksheet_id, rev1)
        self.assertEqual(job_sheet.pinned_by_id, self.approver)
        self.assertFalse(job_sheet.update_available)
        self.assertIn('EC-1 applies to this machine', job_sheet.message_ids[0].body)
        self.assertFalse(request.sudo().activity_ids)
        with self.assertRaisesRegex(UserError, 'no longer pending'):
            request.with_user(self.approver).action_approve()
        # Once decided, another can be asked for.
        self.assertTrue(self._request(job_sheet, 'Back', rev0))

    # Telling the Approvers

    def test_a_request_gives_every_approver_a_todo_that_odoo_announces(self):
        rev0 = self._released()
        job_sheet = self._print(self._create_job(), self.type_general)
        self._new_revision(rev0)
        request = self._request(job_sheet, 'EC-1 applies')
        todos = request.sudo().activity_ids
        self.assertIn(self.approver, todos.user_id)
        todo = todos.filtered(lambda a: a.user_id == self.approver)
        self.assertEqual(todo.summary, f'Approve {request.display_name}')
        self.assertIn('EC-1 applies', todo.note)
        # Odoo itself announces a To-Do to its assignee, in their Inbox or by email; not to the asker.
        self.assertNotIn(self.viewer, todos.user_id)

    def test_a_request_waiting_too_long_reminds_the_approvers_daily(self):
        Change = self.env['qc.job.checksheet.change']
        rev0 = self._released()
        stale_sheet = self._print(self._create_job(), self.type_general)
        fresh_sheet = self._print(self._create_job(), self.type_general)
        self._new_revision(rev0)
        stale = self._request(stale_sheet, 'Old one')
        fresh = self._request(fresh_sheet, 'New one')
        stale.sudo().requested_date = fields.Datetime.now() - timedelta(days=5)

        def todos(request):
            return request.sudo().activity_ids.filtered(lambda a: a.user_id == self.approver)

        self.assertEqual(todos(stale).summary, f'Approve {stale.display_name}')
        Change._cron_remind_approvers()
        # A reminder replaces the To-Do, never piling up, and says how long it has waited.
        self.assertEqual(len(todos(stale)), 1)
        self.assertIn('Still waiting for 5 days', todos(stale).summary)
        # One that is not old enough is left alone, and so is a decided one.
        self.assertEqual(todos(fresh).summary, f'Approve {fresh.display_name}')
        stale.with_user(self.approver).action_cancel()
        Change._cron_remind_approvers()
        self.assertFalse(todos(stale))
        self.assertTrue(self.env.ref('qc_checksheet.cron_remind_pending_revision_changes').active)

    def test_only_an_approver_approves_or_rejects(self):
        rev0 = self._released()
        job_sheet = self._print(self._create_job(), self.type_general)
        self._new_revision(rev0)
        request = self._request(job_sheet)
        with self.assertRaises(AccessError):
            request.with_user(self.viewer).action_approve()
        with self.assertRaises(AccessError):
            request.with_user(self.author).action_reject('No')
        self.assertEqual(request.state, 'pending')
        with self.assertRaises(UserError):
            request.with_user(self.approver).write({'state': 'approved'})

    def test_an_approver_can_approve_their_own_request(self):
        rev0 = self._released()
        job_sheet = self._print(self._create_job(), self.type_general)
        rev1 = self._new_revision(rev0)
        request = self.env['qc.job.checksheet.change'].browse(
            job_sheet.with_user(self.approver).action_request_change('Mine'))
        request.with_user(self.approver).action_approve()
        self.assertEqual(job_sheet.checksheet_id, rev1)

    def test_a_rejected_request_leaves_the_job_alone_and_tells_the_asker(self):
        rev0 = self._released()
        job_sheet = self._print(self._create_job(), self.type_general)
        self._new_revision(rev0)
        request = self._request(job_sheet)
        with self.assertRaisesRegex(UserError, 'reason'):
            request.with_user(self.approver).action_reject(' ')
        request.with_user(self.approver).action_reject('Not for this machine')
        self.assertEqual((request.state, request.reject_reason), ('rejected', 'Not for this machine'))
        self.assertEqual(job_sheet.checksheet_id, rev0)
        self.assertTrue(request.sudo().activity_ids.filtered(lambda a: a.user_id == self.viewer))
        self.assertIn('Not for this machine', job_sheet.message_ids[0].body)

    def test_the_asker_or_an_approver_can_cancel_a_pending_request(self):
        rev0 = self._released()
        job_sheet = self._print(self._create_job(), self.type_general)
        self._new_revision(rev0)
        request = self._request(job_sheet)
        with self.assertRaises(AccessError):
            request.with_user(self.author).action_cancel()
        request.with_user(self.viewer).action_cancel()
        self.assertEqual(request.state, 'cancelled')
        request = self._request(job_sheet)
        request.with_user(self.approver).action_cancel()
        self.assertEqual(request.state, 'cancelled')
        with self.assertRaises(UserError):
            request.with_user(self.viewer).action_cancel()

    def test_a_request_can_pick_any_issued_revision_even_an_older_one(self):
        rev0 = self._released()
        rev1 = self._new_revision(rev0)
        rev2 = self._new_revision(rev1)
        job_sheet = self._print(self._create_job(), self.type_general)
        self.assertEqual(job_sheet.checksheet_id, rev2)
        options = self.JobSheet.job_options(job_sheet.job_id.id, self.type_general.id)
        self.assertEqual([o['revision'] for o in options], [3, 2, 1])
        self.assertEqual([o['pinned'] for o in options], [True, False, False])
        self.assertEqual([o['current'] for o in options], [True, False, False])
        # Not just the newest: a middle Revision, and going back.
        self._request(job_sheet, 'Machine built to Rev 1', rev1).with_user(self.approver).action_approve()
        self.assertEqual(job_sheet.checksheet_id, rev1)
        self._request(job_sheet, 'Back to Rev 0', rev0).with_user(self.approver).action_approve()
        self.assertEqual(job_sheet.checksheet_id, rev0)
        self.assertEqual(job_sheet.latest_revision, 3)
        self.assertTrue(job_sheet.update_available)
        # With no pick, it goes to the current one.
        request = self.env['qc.job.checksheet.change'].browse(job_sheet.with_user(self.viewer).action_request_change('Latest'))
        self.assertEqual(request.to_revision, 3)
        request.with_user(self.approver).action_approve()
        self.assertFalse(job_sheet.update_available)

    def test_a_request_refuses_a_revision_that_is_not_issued_or_not_the_models(self):
        rev0 = self._released()
        job_sheet = self._print(self._create_job(), self.type_general)
        rev1 = rev0.browse(rev0.with_user(self.author).action_create_revision('Draft')['res_id'])
        with self.assertRaisesRegex(UserError, 'not available'):
            self._request(job_sheet, 'To a Draft', rev1)
        other = self._released(self.type_general, self._create_model())
        with self.assertRaisesRegex(UserError, 'not available'):
            self._request(job_sheet, 'Other Model', other)
        with self.assertRaisesRegex(UserError, 'already uses'):
            self._request(job_sheet, 'Same', rev0)

    def test_the_pin_is_not_moved_by_hand(self):
        rev0 = self._released()
        job_sheet = self._print(self._create_job(), self.type_general)
        self._new_revision(rev0)
        self.assertFalse(hasattr(job_sheet, 'action_update_revision'))
        with self.assertRaises(UserError):
            job_sheet.with_user(self.approver).write({'checksheet_id': rev0.id})
        with self.assertRaises(UserError):
            self.env['qc.job.checksheet.change'].with_user(self.approver).create({
                'job_sheet_id': job_sheet.id, 'from_checksheet_id': rev0.id, 'to_checksheet_id': rev0.id, 'reason': 'x'})

    # First pinning

    def test_the_first_pinning_can_choose_any_revision_with_no_approval(self):
        rev0 = self._released()
        rev1 = self._new_revision(rev0)
        job = self._create_job()
        with self.assertRaisesRegex(UserError, 'reason'):
            self.JobSheet.job_pin(job.id, self.type_general.id, rev0.id, ' ')
        options = self.JobSheet.job_options(job.id, self.type_general.id)
        self.assertEqual([(o['revision'], o['pinned']) for o in options], [(2, False), (1, False)])
        job_sheet = self.JobSheet.browse(self.JobSheet.job_pin(job.id, self.type_general.id, rev0.id, 'Built to Rev 0'))
        self.assertEqual(job_sheet.checksheet_id, rev0)
        self.assertIn('Built to Rev 0', job_sheet.message_ids[0].body)
        self.assertNotEqual(job_sheet.checksheet_id, rev1)
        # Once pinned, only a change request moves it.
        with self.assertRaisesRegex(UserError, 'already printed'):
            self.JobSheet.job_pin(job.id, self.type_general.id, rev1.id, 'Again')
        self.assertFalse(self.env['qc.job.checksheet.change'].search([('job_sheet_id', '=', job_sheet.id)]))

    def test_the_first_pinning_refuses_a_revision_that_is_not_issued_or_not_the_models(self):
        rev0 = self._released()
        job = self._create_job()
        draft = rev0.browse(rev0.with_user(self.author).action_create_revision('Draft')['res_id'])
        with self.assertRaisesRegex(UserError, 'not available'):
            self.JobSheet.job_pin(job.id, self.type_general.id, draft.id, 'x')
        other = self._released(self.type_general, self._create_model())
        with self.assertRaisesRegex(UserError, 'not available'):
            self.JobSheet.job_pin(job.id, self.type_general.id, other.id, 'x')

    def test_latest_revision_and_the_outdated_filter(self):
        rev0 = self._released()
        stale = self._print(self._create_job(), self.type_general)
        self._new_revision(rev0)
        fresh = self._print(self._create_job(), self.type_general)
        self.assertEqual((stale.latest_revision, fresh.latest_revision), (2, 2))
        self.assertEqual((stale.revision, fresh.revision), (1, 2))
        outdated = self.env['qc.job.checksheet'].search([('update_available', '=', True)])
        self.assertIn(stale, outdated)
        self.assertNotIn(fresh, outdated)
        current = self.env['qc.job.checksheet'].search([('update_available', '!=', True)])
        self.assertIn(fresh, current)
        self.assertNotIn(stale, current)

    def test_overview_offers_to_change_when_another_revision_is_issued(self):
        rev0 = self._released()
        job = self._create_job()
        job_sheet = self._print(job, self.type_general)
        row = self._row(self.JobSheet.job_overview(job.id), self.type_general)
        self.assertFalse(row['update'])
        self.assertFalse(row['choosable'])
        self._new_revision(rev0)
        row = self._row(self.JobSheet.job_overview(job.id), self.type_general)
        self.assertTrue(row['update'])
        self.assertTrue(row['outdated'])
        self.assertIs(row['pending'], False)
        # A request waiting takes the button away and shows who asked.
        self._request(job_sheet, 'Please')
        row = self._row(self.JobSheet.job_overview(job.id), self.type_general)
        self.assertFalse(row['update'])
        self.assertEqual((row['pending']['revision'], row['pending']['requested_by'], row['pending']['reason']),
                         (2, self.viewer.name, 'Please'))
        self.assertEqual((row['pending']['can_decide'], row['pending']['can_cancel']), (False, True))
        row = self._row(self.env['qc.job.checksheet'].with_user(self.approver).job_overview(job.id), self.type_general)
        self.assertEqual((row['pending']['can_decide'], row['pending']['can_cancel']), (True, True))

    def test_overview_offers_to_choose_a_revision_before_the_first_print(self):
        rev0 = self._released()
        job = self._create_job()
        self.assertFalse(self._row(self.JobSheet.job_overview(job.id), self.type_general)['choosable'])
        self._new_revision(rev0)
        self.assertTrue(self._row(self.JobSheet.job_overview(job.id), self.type_general)['choosable'])

    def test_nothing_to_print_before_the_model_releases_it(self):
        sheet = self._create_checksheet(model=self.model_za90)
        job = self._create_job()
        with self.assertRaisesRegex(UserError, 'no Released'):
            self._print(job, self.type_general)
        self._create_content(sheet)
        self._release(sheet)
        self.assertEqual(self._print(job, self.type_general).checksheet_id, sheet)

    def test_a_job_without_a_model_prints_nothing(self):
        job = self.env['project.project'].create({'name': 'J-NO-MODEL-QC'})
        with self.assertRaisesRegex(UserError, 'no Model'):
            self._print(job, self.type_general)

    def test_the_pin_is_not_written_directly(self):
        rev0 = self._released()
        job_sheet = self._print(self._create_job(), self.type_general)
        with self.assertRaises(UserError):
            job_sheet.write({'checksheet_id': rev0.id})
        with self.assertRaises(UserError):
            self.JobSheet.create({'job_id': job_sheet.job_id.id, 'type_id': self.type_hydraulic.id,
                                  'checksheet_id': rev0.id})
        job_sheet.write({'check_date': '2026-11-06'})
        self.assertEqual(str(job_sheet.check_date), '2026-11-06')

    def test_one_job_sheet_per_type(self):
        rev0 = self._released()
        job_sheet = self._print(self._create_job(), self.type_general)
        with mute_logger('odoo.sql_db'), self.assertRaises(IntegrityError):
            self.env['qc.job.checksheet'].create({
                'job_id': job_sheet.job_id.id, 'type_id': self.type_general.id, 'checksheet_id': rev0.id})
            self.env.flush_all()

    def test_a_pinned_revision_cannot_be_deleted(self):
        rev0 = self._released()
        self._print(self._create_job(), self.type_general)
        with mute_logger('odoo.sql_db'), self.assertRaises(Exception):
            rev0.sudo().root_id.revision_ids.unlink()
            self.env.flush_all()

    # Job QC page

    def test_overview_shows_what_each_type_prints(self):
        rev0 = self._released()
        job = self._create_job(machine_serial='SN-1')
        self._print(job, self.type_general)
        rev1 = self._new_revision(rev0)
        overview = self.JobSheet.job_overview(job.id)

        self.assertEqual(overview['serial'], 'SN-1')
        self.assertEqual(overview['model_id'], self.model_za90.id)
        self.assertEqual((overview['ready'], overview['required']), (1, 2))
        general = self._row(overview, self.type_general)
        self.assertEqual(general['pinned']['id'], rev0.id)
        self.assertEqual(general['current']['id'], rev1.id)
        self.assertTrue(general['update'])
        hydraulic = self._row(overview, self.type_hydraulic)
        self.assertIs(hydraulic['pinned'], False)
        self.assertIs(hydraulic['current'], False)

    def test_overview_offers_an_optional_type_the_model_released(self):
        job = self._create_job()
        self.assertNotIn(self.type_panel.id, [r['type_id'] for r in self.JobSheet.job_overview(job.id)['rows']])
        panel = self._release(self._create_checksheet(self.type_panel, model=self.model_za90))
        row = self._row(self.JobSheet.job_overview(job.id), self.type_panel)
        self.assertFalse(row['required'])
        self.assertEqual(row['current']['id'], panel.id)

    def test_overview_offers_the_current_revision_before_the_first_print(self):
        rev0 = self._released()
        row = self._row(self.JobSheet.job_overview(self._create_job().id), self.type_general)
        self.assertIs(row['pinned'], False)
        self.assertEqual(row['current']['id'], rev0.id)
        self.assertFalse(row['update'])

    def test_overview_of_a_missing_job_says_so(self):
        with self.assertRaisesRegex(UserError, 'no longer exists'):
            self.JobSheet.job_overview(self._create_job().id + 1000)

    def test_progress_counts_what_the_job_can_print(self):
        job = self._create_job()
        self.assertEqual(job.qc_checksheet_progress, '0/2')
        self._released()
        job.invalidate_recordset(['qc_checksheet_progress'])
        self.assertEqual(job.qc_checksheet_progress, '1/2')
        self.assertEqual(job._qc_waiting_for_sheets(), job)
        self._released(self.type_hydraulic)
        job.invalidate_recordset(['qc_checksheet_progress'])
        self.assertEqual(job.qc_checksheet_progress, '2/2')
        self.assertFalse(job._qc_waiting_for_sheets())

    def test_progress_ignores_an_archived_required_type(self):
        job = self._create_job()
        self._released()
        self._released(self.type_hydraulic)
        self.type_hydraulic.active = False
        job.invalidate_recordset(['qc_checksheet_progress'])
        self.assertEqual(job.qc_checksheet_progress, '1/1')

    def test_project_button_opens_the_job_page(self):
        job = self._create_job()
        action = job.action_open_qc_job()
        self.assertEqual(action['tag'], 'qc_checksheet.job')
        self.assertEqual(action['context']['active_id'], job.id)

    # Printing

    def test_a_pending_change_prints_a_warning_until_it_is_decided(self):
        rev0 = self._released()
        job_sheet = self._print(self._create_job(), self.type_general)
        self._new_revision(rev0)
        render = lambda: self.env['ir.actions.report'].with_user(self.viewer)._render_qweb_html(
            'qc_checksheet.report_qc_job_checksheet_document', job_sheet.ids)[0].decode()
        self.assertNotIn('REVISION CHANGE PENDING', render())
        request = self._request(job_sheet)
        html = render()
        self.assertIn('REVISION CHANGE PENDING APPROVAL', html)
        self.assertRegex(html, r'\(REV\s*1\s*TO REV\s*2\)')
        self.assertIn('CHECK WITH QC BEFORE USE', html)
        # The Model's blank print has no Job, so nothing to warn about.
        blank = self.env['ir.actions.report']._render_qweb_html(
            'qc_checksheet.report_qc_checksheet_document', rev0.ids)[0].decode()
        self.assertNotIn('REVISION CHANGE PENDING', blank)
        # The banner makes the header taller, so the page gets a deeper top margin (40 mm otherwise).
        self.assertIn('data-report-margin-top="50"', html)
        self.assertIn('data-report-header-spacing="50"', html)
        request.with_user(self.approver).action_reject('No')
        html = render()
        self.assertNotIn('REVISION CHANGE PENDING', html)
        self.assertNotIn('data-report-margin-top', html)

    def test_a_draft_banner_also_gets_the_deeper_margin(self):
        rev0 = self._released()
        draft = rev0.browse(rev0.with_user(self.author).action_create_revision('Next')['res_id'])
        render = lambda sheet: self.env['ir.actions.report']._render_qweb_html(
            'qc_checksheet.report_qc_checksheet_document', sheet.ids)[0].decode()
        self.assertIn('data-report-margin-top="50"', render(draft))
        self.assertNotIn('data-report-margin-top', render(rev0.sudo().root_id.revision_ids.filtered(
            lambda sheet: sheet.state == 'released')))

    def test_every_print_says_when_and_by_whom_in_the_footer(self):
        rev0 = self._released()
        job_sheet = self._print(self._create_job(), self.type_general)
        report = self.env['ir.actions.report'].with_user(self.viewer)
        for name, ids in (('qc_checksheet.report_qc_job_checksheet_document', job_sheet.ids),
                          ('qc_checksheet.report_qc_checksheet_document', rev0.ids)):
            html = report._render_qweb_html(name, ids)[0].decode()
            self.assertRegex(html, r'Printed\s*<span>\d{2}-[A-Z][a-z]{2}-\d{4} \d{2}:\d{2}</span>\s*·\s*<span>')
            self.assertIn(f'<span>{self.viewer.name}</span>', html)

    def test_the_job_prints_its_pinned_revision_with_its_details_and_no_superseded_banner(self):
        rev0 = self._released()
        partner = self.env['res.partner'].create({'name': 'ACME Co'})
        job = self._create_job(machine_serial='SN-7', engine_serial='EN-7', partner_id=partner.id)
        job_sheet = self._print(job, self.type_general)
        self._new_revision(rev0)
        html = self.env['ir.actions.report'].with_user(self.viewer)._render_qweb_html(
            'qc_checksheet.report_qc_job_checksheet_document', job_sheet.ids)[0].decode()
        for text in ('SN-7', 'EN-7', 'ACME Co', job.name, 'QC-GE-ZA90'):
            self.assertIn(text, html)
        self.assertRegex(html, r'Revision:\s*<span>1</span>')
        self.assertNotIn('SUPERSEDED', html)
        # The same Revision printed from the Model says it's superseded.
        html = self.env['ir.actions.report']._render_qweb_html(
            'qc_checksheet.report_qc_checksheet_document', rev0.ids)[0].decode()
        self.assertIn('SUPERSEDED', html)
