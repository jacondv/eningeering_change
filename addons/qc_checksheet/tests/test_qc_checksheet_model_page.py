from psycopg2 import IntegrityError

from odoo.exceptions import AccessError, UserError
from odoo.tests.common import new_test_user, tagged
from odoo.tools import mute_logger

from .common import QcChecksheetCase


@tagged('post_install', '-at_install')
class TestQcChecksheetModelPage(QcChecksheetCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.author = new_test_user(
            cls.env, login='qc_model_author', groups='base.group_user,qc_checksheet.group_qc_author')
        cls.viewer = new_test_user(cls.env, login='qc_model_viewer', groups='base.group_user')
        cls.type_hydraulic = cls.env['qc.checksheet.type'].create({'name': 'Hydraulic', 'code': 'HY'})
        cls.Sheet = cls.env['qc.checksheet'].with_user(cls.author)

    def _released(self, checksheet_type, model):
        sheet = self._create_checksheet(checksheet_type, model=model)
        if checksheet_type.layout == 'standard':
            self._create_content(sheet, f'{checksheet_type.code} question')
        return self._release(sheet)

    def _row(self, overview, checksheet_type):
        return next(row for row in overview['rows'] if row['type_id'] == checksheet_type.id)

    def test_new_types_are_required_by_default(self):
        self.assertTrue(self.type_hydraulic.required)
        self.assertTrue(self.type_general.required)

    def test_model_progress_counts_required_types_released(self):
        self.type_panel.required = False
        model = self._create_model()
        self.assertEqual(model.qc_checksheet_progress, '0/2')
        self._released(self.type_general, model)
        self._create_checksheet(self.type_hydraulic, model=model)
        self._released(self.type_panel, model)
        model.invalidate_recordset(['qc_checksheet_progress'])
        self.assertEqual(model.qc_checksheet_progress, '1/2')

    def test_overview_lists_required_types_and_what_exists(self):
        self.type_panel.required = False
        self._create_job()
        general = self._released(self.type_general, self.model_za90)
        overview = self.Sheet.model_overview(self.model_za90.id)

        self.assertEqual(overview['job_count'], 1)
        self.assertEqual((overview['released'], overview['required']), (1, 2))
        self.assertEqual([row['type_id'] for row in overview['rows']], [self.type_general.id, self.type_hydraulic.id])
        general_row = self._row(overview, self.type_general)
        self.assertEqual(general_row['current']['id'], general.id)
        self.assertEqual(general_row['number'], 'QC-GE-ZA90')
        self.assertEqual(general_row['jobs'], 0)
        self.assertIs(self._row(overview, self.type_hydraulic)['current'], False)
        self.assertIs(general_row['next'], False)
        self.assertTrue(overview['can_author'])

    def test_overview_counts_the_jobs_that_printed_a_sheet(self):
        self._released(self.type_general, self.model_za90)
        for job in self._create_job() | self._create_job():
            self.env['qc.job.checksheet'].job_print(job.id, [self.type_general.id])
        row = self._row(self.Sheet.model_overview(self.model_za90.id), self.type_general)
        self.assertEqual(row['jobs'], 2)

    def test_overview_counts_jobs_on_an_old_revision(self):
        rev0 = self._released(self.type_general, self.model_za90)
        old_job = self._create_job()
        self.env['qc.job.checksheet'].job_print(old_job.id, [self.type_general.id])
        rev1 = rev0.browse(rev0.action_create_revision('Change')['res_id'])
        rev1.action_submit()
        rev1.action_approve()
        self.env['qc.job.checksheet'].job_print(self._create_job().id, [self.type_general.id])
        row = self._row(self.Sheet.model_overview(self.model_za90.id), self.type_general)
        self.assertEqual((row['jobs'], row['old_jobs']), (2, 1))

    def test_a_sheet_lists_the_jobs_using_any_of_its_revisions(self):
        rev0 = self._released(self.type_general, self.model_za90)
        old_job = self._create_job()
        self.env['qc.job.checksheet'].job_print(old_job.id, [self.type_general.id])
        rev1 = rev0.browse(rev0.action_create_revision('Change')['res_id'])
        rev1.action_submit()
        rev1.action_approve()
        new_job = self._create_job()
        self.env['qc.job.checksheet'].job_print(new_job.id, [self.type_general.id])
        # Per Revision, and for the whole sheet from either Revision.
        self.assertEqual((rev0.job_count, rev1.job_count), (1, 1))
        for sheet in (rev0, rev1):
            self.assertEqual(sheet.sheet_job_count, 2)
            self.assertEqual(sheet.root_job_sheet_ids.job_id, old_job | new_job)
            action = sheet.action_view_jobs()
            self.assertEqual(self.env['qc.job.checksheet'].search(action['domain']).job_id, old_job | new_job)
        self.assertEqual(rev1.editor_load()['job_count'], 2)
        # Closed Jobs are listed too, with their status to filter on.
        old_job.last_update_status = 'eol'
        job_sheet = self.env['qc.job.checksheet'].search([('job_id', '=', old_job.id)])
        self.assertEqual(job_sheet.job_status, 'eol')
        open_ones = self.env['qc.job.checksheet'].search(
            [('root_id', '=', rev0.root_id.id), ('job_status', 'in', ['in_progress', 'on_hold'])])
        self.assertEqual(open_ones.job_id, new_job)

    def test_the_job_count_of_a_sheet_follows_a_job_pinned_in_the_same_transaction(self):
        rev0 = self._released(self.type_general, self.model_za90)
        self.assertEqual(rev0.sheet_job_count, 0)
        self.assertFalse(rev0.root_job_sheet_ids)
        job = self._create_job()
        self.env['qc.job.checksheet'].job_print(job.id, [self.type_general.id])
        self.assertEqual(rev0.sheet_job_count, 1)
        self.assertEqual(rev0.root_job_sheet_ids.job_id, job)
        # One batch for many sheets, each with its own Jobs.
        other = self._released(self.type_general, self._create_model())
        both = rev0 | other
        self.assertEqual(both.mapped('sheet_job_count'), [1, 0])

    def test_overview_shows_an_optional_type_once_used(self):
        self.type_panel.required = False
        model = self._create_model()
        self._create_checksheet(self.type_panel, model=model)
        row = self._row(self.Sheet.model_overview(model.id), self.type_panel)
        self.assertFalse(row['required'])
        self.assertEqual(row['current']['state'], 'draft')

    def test_overview_shows_the_revision_in_use_and_the_one_in_progress(self):
        model = self._create_model()
        rev0 = self._released(self.type_general, model)
        rev1 = rev0.browse(rev0.action_create_revision('Change')['res_id'])
        row = self._row(self.Sheet.model_overview(model.id), self.type_general)
        self.assertEqual(row['current']['id'], rev0.id)
        self.assertEqual(row['next']['id'], rev1.id)
        self.assertEqual(row['next']['state'], 'draft')

    def test_copy_sources_are_the_other_models_with_a_released_sheet_of_the_same_type(self):
        other = self._create_model('M-COPY-1')
        self._released(self.type_hydraulic, other)
        model = self._create_model()
        own = self._create_model('M-COPY-OWN')
        self._released(self.type_hydraulic, own)
        # Never a sheet of another Type, even with the same layout, and never one still a Draft.
        self._released(self.type_general, self._create_model('M-COPY-GENERAL'))
        self._create_checksheet(self.type_hydraulic, model=self._create_model('M-COPY-DRAFT'))
        found = self.Sheet.model_copy_sources(self.type_hydraulic.id, own.id, 'M-COPY')
        self.assertEqual([m['name'] for m in found], ['M-COPY-1'])
        self.assertEqual([m['name'] for m in self.Sheet.model_copy_sources(self.type_hydraulic.id, model.id, 'M-COPY-O')],
                         ['M-COPY-OWN'])

    def test_a_sheet_is_copied_from_the_released_sheet_of_the_model_picked(self):
        source = self._released(self.type_hydraulic, self._create_model('M-FROM'))
        created = self.Sheet.model_create_sheets(self._create_model().id, [{
            'type_id': self.type_hydraulic.id, 'header': 'Copied', 'source_model_id': source.model_id.id}])
        copy = self.env['qc.checksheet'].browse(created[0]['id'])
        self.assertEqual(copy.copied_from_id, source)
        self.assertIn('HY question', copy.group_ids.item_ids.description)

    def test_nothing_is_copied_from_a_model_with_no_released_sheet_of_the_type(self):
        self._released(self.type_general, self._create_model('M-OTHER-TYPE'))
        with self.assertRaises(UserError):
            self.Sheet.model_create_sheets(self._create_model().id, [{
                'type_id': self.type_hydraulic.id, 'header': 'X',
                'source_model_id': self.env['equipment.model'].search([('name', '=', 'M-OTHER-TYPE')]).id}])

    def test_sources_give_the_model_whose_name_is_extended(self):
        base = self._create_model('M-BASE')
        self._released(self.type_hydraulic, base)
        row = self.Sheet.model_sheet_sources(self._create_model('M-BASE-068').id, [self.type_hydraulic.id])[0]
        self.assertEqual(row['share_model']['id'], base.id)
        row = self.Sheet.model_sheet_sources(self._create_model('M-ALONE').id, [self.type_hydraulic.id])[0]
        self.assertFalse(row['share_model'])

    def test_sources_offer_the_family_header(self):
        category = self.env['equipment.model.category'].create({'name': 'Category'})
        self.model_za90.family_id = self.env['equipment.model.family'].create({
            'name': 'Family', 'description': 'Loader', 'category_id': category.id,
        })
        source = self.Sheet.model_sheet_sources(self.model_za90.id, [self.type_hydraulic.id])[0]
        self.assertEqual(source['header'], 'Loader')

    def test_create_sheets_creates_them_all(self):
        source = self._released(self.type_hydraulic, self._create_model())
        model = self._create_model()
        created = self.Sheet.model_create_sheets(model.id, [
            {'type_id': self.type_general.id, 'header': 'General', 'source_id': False},
            {'type_id': self.type_hydraulic.id, 'header': 'Hydraulic', 'source_model_id': source.model_id.id},
        ])
        sheets = self.env['qc.checksheet'].browse([c['id'] for c in created])
        self.assertEqual(sheets.mapped('type_id'), self.type_general | self.type_hydraulic)
        self.assertEqual(sheets.model_id, model)
        self.assertEqual(set(sheets.mapped('revision')), {1})
        self.assertEqual(set(sheets.mapped('state')), {'draft'})
        hydraulic = sheets.filtered(lambda s: s.type_id == self.type_hydraulic)
        self.assertEqual(hydraulic.copied_from_id, source)
        self.assertIn('HY question', hydraulic.group_ids.item_ids.description)

    def test_create_sheets_is_all_or_nothing(self):
        model = self._create_model()
        self._create_checksheet(self.type_hydraulic, model=model)
        with mute_logger('odoo.sql_db'), self.assertRaises(IntegrityError):
            self.Sheet.model_create_sheets(model.id, [
                {'type_id': self.type_general.id, 'header': 'General'},
                {'type_id': self.type_hydraulic.id, 'header': 'Hydraulic'},
            ])
            self.env.flush_all()

    def test_viewer_sees_the_page_but_cannot_create(self):
        model = self._create_model()
        Sheet = self.env['qc.checksheet'].with_user(self.viewer)
        self.assertFalse(Sheet.model_overview(model.id)['can_author'])
        with self.assertRaises(AccessError):
            Sheet.model_create_sheets(model.id, [{'type_id': self.type_general.id, 'header': 'X'}])

    def test_overview_of_a_missing_model_says_so(self):
        missing_id = self._create_model().id + 1000
        with self.assertRaisesRegex(UserError, 'no longer exists'):
            self.Sheet.model_overview(missing_id)

    def test_an_archived_type_keeps_showing_the_sheets_of_a_model(self):
        model = self._create_model()
        sheet = self._released(self.type_hydraulic, model)
        self.type_hydraulic.active = False
        row = self._row(self.Sheet.model_overview(model.id), self.type_hydraulic)
        self.assertEqual(row['current']['id'], sheet.id)

    def test_model_button_opens_the_model_page(self):
        action = self.model_za90.action_open_qc_model()
        self.assertEqual(action['tag'], 'qc_checksheet.model')
        self.assertEqual(action['context']['active_id'], self.model_za90.id)
