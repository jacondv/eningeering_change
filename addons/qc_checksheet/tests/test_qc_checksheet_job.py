from psycopg2 import IntegrityError

from odoo.exceptions import AccessError
from odoo.tests.common import new_test_user, tagged
from odoo.tools import mute_logger

from .common import QcChecksheetCase


@tagged('post_install', '-at_install')
class TestQcChecksheetJob(QcChecksheetCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.author = new_test_user(
            cls.env, login='qc_job_author', groups='base.group_user,qc_checksheet.group_qc_author')
        cls.viewer = new_test_user(cls.env, login='qc_job_viewer', groups='base.group_user')
        cls.type_hydraulic = cls.env['qc.checksheet.type'].create({'name': 'Hydraulic', 'code': 'HY'})
        cls.Sheet = cls.env['qc.checksheet'].with_user(cls.author)

    def _released(self, checksheet_type, job):
        sheet = self._create_checksheet(checksheet_type, job=job)
        if checksheet_type.layout == 'standard':
            self._create_content(sheet, f'{checksheet_type.code} question')
        return self._release(sheet)

    def _row(self, overview, checksheet_type):
        return next(row for row in overview['rows'] if row['type_id'] == checksheet_type.id)

    def test_new_types_are_required_by_default(self):
        self.assertTrue(self.type_hydraulic.required)
        self.assertTrue(self.type_general.required)

    def test_progress_counts_required_types_released(self):
        self.type_panel.required = False
        job = self._create_job()
        self.assertEqual(job.qc_checksheet_progress, '0/2')
        self._released(self.type_general, job)
        self._create_checksheet(self.type_hydraulic, job=job)
        self._released(self.type_panel, job)
        job.invalidate_recordset(['qc_checksheet_progress'])
        self.assertEqual(job.qc_checksheet_progress, '1/2')

    def test_overview_lists_required_types_and_what_exists(self):
        self.type_panel.required = False
        job = self._create_job(machine_serial='SN-1')
        general = self._released(self.type_general, job)
        overview = self.Sheet.job_overview(job.id)

        self.assertEqual(overview['serial'], 'SN-1')
        self.assertEqual((overview['released'], overview['required']), (1, 2))
        self.assertEqual([row['type_id'] for row in overview['rows']], [self.type_general.id, self.type_hydraulic.id])
        general_row = self._row(overview, self.type_general)
        self.assertEqual(general_row['current']['id'], general.id)
        self.assertEqual(general_row['number'], 'QC-GE-ZA90')
        self.assertIs(self._row(overview, self.type_hydraulic)['current'], False)
        self.assertIs(general_row['next'], False)
        self.assertTrue(overview['can_author'])

    def test_overview_shows_an_optional_type_once_used(self):
        self.type_panel.required = False
        job = self._create_job()
        self._create_checksheet(self.type_panel, job=job)
        row = self._row(self.Sheet.job_overview(job.id), self.type_panel)
        self.assertFalse(row['required'])
        self.assertEqual(row['current']['state'], 'draft')

    def test_overview_shows_the_revision_in_use_and_the_one_in_progress(self):
        job = self._create_job()
        rev0 = self._released(self.type_general, job)
        rev1 = rev0.browse(rev0.action_create_revision('Change')['res_id'])
        row = self._row(self.Sheet.job_overview(job.id), self.type_general)
        self.assertEqual(row['current']['id'], rev0.id)
        self.assertEqual(row['next']['id'], rev1.id)
        self.assertEqual(row['next']['state'], 'draft')

    def test_sources_prefer_same_type_then_same_model(self):
        other_model = self.env['equipment.model'].create({'name': 'ZB10'})
        other_model_hy = self._released(self.type_hydraulic, self._create_job(model=other_model))
        same_model_hy = self._released(self.type_hydraulic, self._create_job())
        general = self._released(self.type_general, self._create_job())
        job = self._create_job()

        source = self.Sheet.job_sheet_sources(job.id, [self.type_hydraulic.id])[0]

        self.assertEqual(source['source_id'], same_model_hy.id)
        ids = [option['id'] for option in source['options']]
        self.assertEqual(ids[:2], [same_model_hy.id, other_model_hy.id])
        self.assertIn(general.id, ids)
        self.assertFalse(next(o for o in source['options'] if o['id'] == general.id)['same_type'])

    def test_sources_fall_back_to_another_model_then_blank(self):
        other_model = self.env['equipment.model'].create({'name': 'ZB10'})
        other_model_hy = self._released(self.type_hydraulic, self._create_job(model=other_model))
        self._released(self.type_general, self._create_job())
        job = self._create_job()
        sources = self.Sheet.job_sheet_sources(job.id, [self.type_hydraulic.id, self.type_panel.id])
        self.assertEqual(sources[0]['source_id'], other_model_hy.id)
        self.assertFalse(sources[1]['source_id'])

    def test_sources_never_mix_layouts(self):
        panel = self._released(self.type_panel, self._create_job())
        general = self._released(self.type_general, self._create_job())
        job = self._create_job()
        ids = [o['id'] for o in self.Sheet.job_sheet_sources(job.id, [self.type_hydraulic.id])[0]['options']]
        self.assertIn(general.id, ids)
        self.assertNotIn(panel.id, ids)

    def test_sources_offer_the_family_header(self):
        category = self.env['equipment.model.category'].create({'name': 'Category'})
        self.model_za90.family_id = self.env['equipment.model.family'].create({
            'name': 'Family', 'description': 'Loader', 'category_id': category.id,
        })
        source = self.Sheet.job_sheet_sources(self._create_job().id, [self.type_hydraulic.id])[0]
        self.assertEqual(source['header'], 'Loader')

    def test_create_sheets_creates_them_all(self):
        source = self._released(self.type_hydraulic, self._create_job())
        job = self._create_job()
        created = self.Sheet.job_create_sheets(job.id, [
            {'type_id': self.type_general.id, 'header': 'General', 'source_id': False},
            {'type_id': self.type_hydraulic.id, 'header': 'Hydraulic', 'source_id': source.id},
        ])
        sheets = self.env['qc.checksheet'].browse([c['id'] for c in created])
        self.assertEqual(sheets.mapped('type_id'), self.type_general | self.type_hydraulic)
        self.assertEqual(set(sheets.mapped('revision')), {0})
        self.assertEqual(set(sheets.mapped('state')), {'draft'})
        hydraulic = sheets.filtered(lambda s: s.type_id == self.type_hydraulic)
        self.assertEqual(hydraulic.copied_from_id, source)
        self.assertIn('HY question', hydraulic.group_ids.item_ids.description)
        self.assertEqual(self.Sheet.job_overview(job.id)['required'], 3)

    def test_create_sheets_is_all_or_nothing(self):
        job = self._create_job()
        self._create_checksheet(self.type_hydraulic, job=job)
        with mute_logger('odoo.sql_db'), self.assertRaises(IntegrityError):
            self.Sheet.job_create_sheets(job.id, [
                {'type_id': self.type_general.id, 'header': 'General'},
                {'type_id': self.type_hydraulic.id, 'header': 'Hydraulic'},
            ])
            self.env.flush_all()

    def test_viewer_sees_the_page_but_cannot_create(self):
        job = self._create_job()
        Sheet = self.env['qc.checksheet'].with_user(self.viewer)
        self.assertFalse(Sheet.job_overview(job.id)['can_author'])
        with self.assertRaises(AccessError):
            Sheet.job_create_sheets(job.id, [{'type_id': self.type_general.id, 'header': 'X'}])

    def test_project_button_opens_the_job_page(self):
        job = self._create_job()
        action = job.action_open_qc_job()
        self.assertEqual(action['tag'], 'qc_checksheet.job')
        self.assertEqual(action['context']['active_id'], job.id)
