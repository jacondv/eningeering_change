from odoo.exceptions import AccessError, UserError
from odoo.tests.common import new_test_user, tagged

from .common import QcChecksheetCase


@tagged('post_install', '-at_install')
class TestQcChecksheetShare(QcChecksheetCase):
    """A Model uses another Model's sheet of a Type: JSV6-EMU-A-068 prints the sheet of JSV6-EMU-A."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(
            cls.env, login='qc_share_user', groups='base.group_user,qc_checksheet.group_qc_user')
        cls.author = new_test_user(
            cls.env, login='qc_share_author', groups='base.group_user,qc_checksheet.group_qc_author')
        cls.approver = new_test_user(
            cls.env, login='qc_share_approver', groups='base.group_user,qc_checksheet.group_qc_approver')
        cls.outsider = new_test_user(cls.env, login='qc_share_outsider', groups='base.group_portal')
        cls.type_panel.required = False
        cls.base = cls.env['equipment.model'].create({'name': 'SH-EMU-A'})
        cls.variant = cls.env['equipment.model'].create({'name': 'SH-EMU-A-068'})
        cls.Sheet = cls.env['qc.checksheet']
        cls.JobSheet = cls.env['qc.job.checksheet'].with_user(cls.user)
        cls.Share = cls.env['qc.checksheet.share']

    def _released(self, model=None, content='Check oil level', checksheet_type=None):
        sheet = self._create_checksheet(checksheet_type, model=model or self.base)
        self._create_content(sheet, content)
        return self._release(sheet)

    def _new_revision(self, sheet, content=None):
        rev = sheet.browse(sheet.with_user(self.author).action_create_revision('Change')['res_id'])
        if content:
            rev.group_ids.item_ids.write({'description': content})
        rev.with_user(self.author).action_submit()
        rev.with_user(self.approver).action_approve()
        return rev

    def _share(self, model=None, source=None, checksheet_type=None):
        return self.Sheet.with_user(self.user).model_share(
            (model or self.variant).id, (checksheet_type or self.type_general).id, (source or self.base).id)

    def _print(self, job):
        return self.JobSheet.browse(self.JobSheet.job_print(job.id, [self.type_general.id]))

    # Resolving

    def test_a_job_of_the_model_prints_and_pins_the_sheet_it_uses(self):
        sheet = self._released()
        self._share()
        job = self._create_job(model=self.variant)
        pinned = self._print(job)
        self.assertEqual(pinned.checksheet_id, sheet)
        self.assertEqual(pinned.model_id, self.base)
        row = next(r for r in self.JobSheet.job_overview(job.id)['rows'] if r['type_id'] == self.type_general.id)
        self.assertEqual(row['shared_from'], 'SH-EMU-A')
        self.assertFalse(row['pinned']['other_model'])
        self.assertEqual(row['current']['id'], sheet.id)

    def test_a_model_with_no_sheet_of_its_own_cannot_print_before_the_source_is_released(self):
        self._create_checksheet(model=self.base)
        self._share()
        job = self._create_job(model=self.variant)
        with self.assertRaises(UserError):
            self._print(job)

    def test_a_new_release_of_the_source_reaches_the_jobs_of_both_models(self):
        rev0 = self._released()
        self._share()
        job = self._create_job(model=self.variant)
        own_job = self._create_job(model=self.base)
        pinned, own_pinned = self._print(job), self._print(own_job)
        rev1 = self._new_revision(rev0, 'Check oil and filter')
        for job_sheet in (pinned, own_pinned):
            job_sheet.invalidate_recordset()
            self.assertEqual((job_sheet.revision, job_sheet.latest_revision, job_sheet.update_available), (1, 2, True))
        # The variant's Job moves to Rev 1 like any other: by a request an Approver approves.
        request = self.env['qc.job.checksheet.change'].browse(pinned.action_request_change('New limit'))
        request.with_user(self.approver).action_approve()
        self.assertEqual(pinned.checksheet_id, rev1)
        self.assertEqual(sorted(self.JobSheet.job_options(job.id, self.type_general.id), key=lambda o: o['revision'])[-1]['id'], rev1.id)

    def test_progress_counts_the_sheet_of_the_source(self):
        self._released()
        self._share()
        job = self._create_job(model=self.variant)
        (self.variant | self.base).invalidate_recordset()
        job.invalidate_recordset()
        self.assertEqual(self.variant.qc_checksheet_progress, '1/1')
        self.assertEqual(job.qc_checksheet_progress, '1/1')

    # Rules

    def test_only_a_model_with_no_sheet_of_its_own_can_use_another(self):
        self._released()
        self._released(model=self.variant)
        with self.assertRaises(UserError):
            self._share()

    def test_the_source_needs_a_sheet_and_it_is_not_the_model_itself(self):
        with self.assertRaises(UserError):
            self._share()
        self._released()
        with self.assertRaises(UserError):
            self._share(model=self.base, source=self.base)

    def test_a_sheet_is_shared_one_level_only(self):
        self._released()
        third = self.env['equipment.model'].create({'name': 'SH-EMU-A-069'})
        self._share()
        with self.assertRaises(UserError):
            self._share(model=third, source=self.variant)
        with self.assertRaises(UserError):
            self._share(model=self.base, source=third)

    def test_a_model_using_a_sheet_cannot_create_one_of_its_own_by_the_side(self):
        self._released()
        self._share()
        with self.assertRaises(UserError):
            self.Sheet.with_user(self.author).editor_create({
                'model_id': self.variant.id, 'type_id': self.type_general.id, 'header': 'X'})

    def test_who_can_change_the_link(self):
        self._released()
        with self.assertRaises(AccessError):
            self.Sheet.with_user(self.outsider).model_share(self.variant.id, self.type_general.id, self.base.id)
        self._share()
        self.assertTrue(self.Share.search([('model_id', '=', self.variant.id)]))

    # The Model page

    def test_the_model_page_shows_where_a_sheet_comes_from_and_who_uses_it(self):
        sheet = self._released()
        self._share()
        row = next(r for r in self.Sheet.with_user(self.user).model_overview(self.variant.id)['rows']
                   if r['type_id'] == self.type_general.id)
        self.assertEqual(row['shared_from'], {'model_id': self.base.id, 'name': 'SH-EMU-A'})
        self.assertEqual(row['current']['id'], sheet.id)
        owner_row = next(r for r in self.Sheet.with_user(self.user).model_overview(self.base.id)['rows']
                         if r['type_id'] == self.type_general.id)
        self.assertEqual(owner_row['shared_with'], ['SH-EMU-A-068'])
        self.assertFalse(owner_row['shared_from'])
        overview = self.Sheet.with_user(self.user).model_overview(self.variant.id)
        self.assertEqual((overview['released'], overview['required']), (1, 1))

    def test_the_editor_says_which_models_use_the_sheet(self):
        sheet = self._released()
        self._share()
        self.assertEqual(sheet.with_user(self.author).editor_load()['shared_models'], ['SH-EMU-A-068'])

    def test_jobs_of_a_model_using_a_sheet_are_counted_on_the_page(self):
        self._released()
        self._share()
        self._print(self._create_job(model=self.variant))
        self._print(self._create_job(model=self.base))
        row = next(r for r in self.Sheet.with_user(self.user).model_overview(self.variant.id)['rows']
                   if r['type_id'] == self.type_general.id)
        self.assertEqual(row['jobs'], 1)

    def test_creating_a_missing_sheet_offers_the_model_whose_name_it_extends_as_the_one_to_use(self):
        self._released()
        row = self.Sheet.with_user(self.user).model_sheet_sources(self.variant.id, [self.type_general.id])[0]
        self.assertEqual(row['share_model']['id'], self.base.id)
        unrelated = self.env['equipment.model'].create({'name': 'ZZ-OTHER'})
        row = self.Sheet.with_user(self.user).model_sheet_sources(unrelated.id, [self.type_general.id])[0]
        self.assertFalse(row['share_model'])
        # Any Model with a sheet can still be searched and picked.
        found = self.Sheet.with_user(self.user).model_share_sources(self.type_general.id, unrelated.id, 'SH-EMU')
        self.assertEqual([m['id'] for m in found], [self.base.id])

    def test_the_create_dialog_can_use_another_models_sheet_instead_of_creating_one(self):
        sheet = self._released()
        created = self.Sheet.with_user(self.user).model_create_sheets(self.variant.id, [
            {'type_id': self.type_general.id, 'share_model_id': self.base.id}])
        self.assertEqual(created[0]['id'], False)
        self.assertEqual(self.Share._owner(self.variant, self.type_general), self.base)
        self.assertEqual(self.Sheet.search([('model_id', '=', self.variant.id)]), self.Sheet)
        self.assertTrue(sheet.exists())
        # Writing a sheet still needs an Author.
        other = self.env['equipment.model'].create({'name': 'SH-ANOTHER'})
        with self.assertRaises(AccessError):
            self.Sheet.with_user(self.user).model_create_sheets(other.id, [
                {'type_id': self.type_general.id, 'header': 'X'}])

    def test_the_longest_name_beginning_wins_and_a_model_without_a_sheet_is_not_suggested(self):
        self._released()
        middle = self.env['equipment.model'].create({'name': 'SH-EMU'})
        self.assertEqual(self.Share._suggest_source(self.variant, self.type_general), self.base)
        self._released(model=middle)
        self.assertEqual(self.Share._suggest_source(self.variant, self.type_general), self.base)

    # Taking a sheet away, to set it up again

    def test_deleting_a_shared_sheet_removes_only_the_link(self):
        sheet = self._released()
        self._share()
        self.Sheet.with_user(self.user).model_delete_sheets(self.variant.id, [self.type_general.id])
        self.assertFalse(self.Share.search([('model_id', '=', self.variant.id)]))
        self.assertTrue(sheet.exists())

    def test_a_job_keeps_its_pin_when_the_link_to_its_sheet_is_removed(self):
        sheet = self._released()
        self._share()
        pinned = self._print(self._create_job(model=self.variant))
        self.Sheet.with_user(self.user).model_delete_sheets(self.variant.id, [self.type_general.id])
        self.assertEqual(pinned.checksheet_id, sheet)

    def test_an_author_deletes_a_draft_sheet_of_the_model(self):
        draft = self._create_checksheet(model=self.variant)
        self.Sheet.with_user(self.author).model_delete_sheets(self.variant.id, [self.type_general.id])
        self.assertFalse(draft.exists())

    def test_a_released_sheet_is_deleted_by_a_qc_administrator_only(self):
        admin = new_test_user(self.env, login='qc_share_admin', groups='base.group_user,qc_checksheet.group_qc_admin')
        released = self._released(model=self.variant)
        with self.assertRaises(UserError):
            self.Sheet.with_user(self.author).model_delete_sheets(self.variant.id, [self.type_general.id])
        self.assertTrue(released.exists())
        self.Sheet.with_user(admin).model_delete_sheets(self.variant.id, [self.type_general.id])
        self.assertFalse(released.exists())

    def test_a_sheet_a_job_printed_cannot_be_deleted(self):
        admin = new_test_user(self.env, login='qc_share_admin2', groups='base.group_user,qc_checksheet.group_qc_admin')
        released = self._released(model=self.variant)
        self._print(self._create_job(model=self.variant))
        with self.assertRaises(UserError):
            self.Sheet.with_user(admin).model_delete_sheets(self.variant.id, [self.type_general.id])
        self.assertTrue(released.exists())

    def test_a_sheet_other_models_use_cannot_be_deleted(self):
        admin = new_test_user(self.env, login='qc_share_admin3', groups='base.group_user,qc_checksheet.group_qc_admin')
        released = self._released()
        self._share()
        with self.assertRaises(UserError):
            self.Sheet.with_user(admin).model_delete_sheets(self.base.id, [self.type_general.id])
        self.assertTrue(released.exists())

    def test_deleting_then_creating_again_changes_the_sheet_a_model_uses(self):
        other = self.env['equipment.model'].create({'name': 'SH-OTHER'})
        self._released()
        self._released(model=other)
        self._share()
        self.Sheet.with_user(self.user).model_delete_sheets(self.variant.id, [self.type_general.id])
        self._share(source=other)
        self.assertEqual(self.Share._owner(self.variant, self.type_general), other)

    # Merging sheets that print the same

    def _twins(self):
        """Two Models with their own sheet of the same content: the base, and the variant."""
        return self._released(), self._released(model=self.variant)

    def test_the_page_offers_to_merge_a_sheet_into_one_that_prints_the_same(self):
        self._twins()
        row = next(r for r in self.Sheet.with_user(self.user).model_overview(self.variant.id)['rows']
                   if r['type_id'] == self.type_general.id)
        self.assertEqual(row['same_as'], [{'model_id': self.base.id, 'name': 'SH-EMU-A'}])
        self._released(model=self.env['equipment.model'].create({'name': 'SH-DIFF'}), content='Another question')
        row = next(r for r in self.Sheet.with_user(self.user).model_overview(self.variant.id)['rows']
                   if r['type_id'] == self.type_general.id)
        self.assertEqual([m['name'] for m in row['same_as']], ['SH-EMU-A'])

    def test_a_sheet_that_prints_differently_is_not_offered(self):
        self._released()
        self._released(model=self.variant, content='A different question')
        row = next(r for r in self.Sheet.with_user(self.user).model_overview(self.variant.id)['rows']
                   if r['type_id'] == self.type_general.id)
        self.assertEqual(row['same_as'], [])

    def test_merging_moves_the_jobs_scans_and_requests_to_the_identical_revision(self):
        base, own = self._twins()
        job = self._create_job(model=self.variant)
        pinned = self._print(job)
        self.assertEqual(pinned.checksheet_id, own)
        self.Sheet.with_user(self.author).model_merge(self.variant.id, self.type_general.id, self.base.id)
        self.assertFalse(own.exists())
        self.assertEqual(pinned.checksheet_id, base)
        self.assertEqual(self.Share._owner(self.variant, self.type_general), self.base)
        self.assertIn('merged into', pinned.message_ids[0].body)
        # The Job is a Job of the shared sheet from then on.
        self.assertEqual(self._print(self._create_job(model=self.variant)).checksheet_id, base)

    def test_merging_keeps_a_scan_on_the_moved_revision(self):
        base, own = self._twins()
        pinned = self._print(self._create_job(model=self.variant))
        scan = self.env['qc.job.checksheet.scan'].sudo().create({
            'job_sheet_id': pinned.id, 'checksheet_id': own.id, 'check_date': '2026-01-05'})
        self.Sheet.with_user(self.author).model_merge(self.variant.id, self.type_general.id, self.base.id)
        self.assertEqual((scan.checksheet_id, pinned.inspection_state), (base, 'scanned'))

    def test_a_revision_in_use_with_no_identical_one_on_the_other_side_stops_the_merge(self):
        base, own = self._twins()
        self._print(self._create_job(model=self.variant))
        self._new_revision(own, 'Only here')
        own.invalidate_recordset()
        # The variant's current Release now differs from the base's.
        with self.assertRaises(UserError):
            self.Sheet.with_user(self.author).model_merge(self.variant.id, self.type_general.id, self.base.id)
        self.assertTrue(own.exists())

    def test_merging_needs_identical_current_sheets_and_an_author(self):
        self._released()
        self._released(model=self.variant, content='A different question')
        with self.assertRaises(UserError):
            self.Sheet.with_user(self.author).model_merge(self.variant.id, self.type_general.id, self.base.id)
        with self.assertRaises(AccessError):
            self.Sheet.with_user(self.user).model_merge(self.variant.id, self.type_general.id, self.base.id)

    def test_a_revision_still_being_written_stops_the_merge(self):
        base, own = self._twins()
        own.with_user(self.author).action_create_revision('In progress')
        with self.assertRaises(UserError):
            self.Sheet.with_user(self.author).model_merge(self.variant.id, self.type_general.id, self.base.id)

    def test_a_model_other_models_use_cannot_be_merged_away(self):
        self._twins()
        third = self.env['equipment.model'].create({'name': 'SH-EMU-A-070'})
        self.Share.sudo().create({
            'model_id': third.id, 'type_id': self.type_general.id, 'source_model_id': self.variant.id})
        with self.assertRaises(UserError):
            self.Sheet.with_user(self.author).model_merge(self.variant.id, self.type_general.id, self.base.id)
