import base64
import io
import uuid

import openpyxl

from odoo.exceptions import AccessError, UserError
from odoo.tests.common import tagged

from .common import EquipmentModelCase

HEADER = ['Group', 'Product Family', 'Model', 'Parent Model', 'Job']


@tagged('post_install', '-at_install')
class TestImportExport(EquipmentModelCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.job = cls.env['project.project'].create({'name': 'TS100-001'})
        # Importing is for Managers: run the tests as one, not as the superuser.
        cls.manager = cls._create_user('equipment_model.group_equipment_model_manager', 'project.group_project_manager')
        cls.env = cls.env(user=cls.manager)

    @classmethod
    def _create_user(cls, *groups):
        return cls.env['res.users'].sudo().create({
            'name': 'Import tester',
            'login': f"import_{uuid.uuid4().hex[:8]}",
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id] + [cls.env.ref(group).id for group in groups])],
        })

    def workbook(self, rows, header=HEADER):
        book = openpyxl.Workbook()
        sheet = book.active
        sheet.append(header)
        for row in rows:
            sheet.append(row)
        buffer = io.BytesIO()
        book.save(buffer)
        return base64.b64encode(buffer.getvalue())

    def wizard(self, rows, **kwargs):
        return self.env['equipment.model.import.wizard'].create({'file': self.workbook(rows, **kwargs), 'filename': 'x.xlsx'})

    def preview(self, rows):
        wizard = self.wizard(rows)
        wizard.action_preview()
        return wizard

    def lines(self, wizard):
        return sorted((line.row, line.status) for line in wizard.line_ids)

    def counts(self):
        return tuple(self.env[name].search_count([]) for name in
                     ('equipment.model.category', 'equipment.model.family', 'equipment.model'))

    def test_preview_saves_nothing(self):
        before = self.counts()
        wizard = self.preview([['New Group', 'NF1', 'NF1-A', '', '']])
        self.assertEqual(self.lines(wizard), [(2, 'create')])
        self.assertEqual(wizard.create_count, 1)
        self.assertEqual(self.counts(), before)
        self.assertFalse(self.env['equipment.model'].search([('name', '=', 'NF1-A')]))

    def test_apply_creates_the_whole_chain(self):
        wizard = self.preview([['New Group', 'NF1', 'NF1-A', '', '']])
        wizard.action_apply()
        model = self.env['equipment.model'].search([('name', '=', 'NF1-A')])
        self.assertEqual(model.family_id.name, 'NF1')
        self.assertEqual(model.family_id.category_id.name, 'New Group')
        self.assertEqual(wizard.state, 'done')

    def test_existing_names_are_matched_ignoring_case_not_duplicated(self):
        before = self.counts()
        wizard = self.preview([['test group 01', 'ts100', 'ts100-a', '', '']])
        self.assertEqual(self.lines(wizard), [(2, 'unchanged')])
        wizard.action_apply()
        self.assertEqual(self.counts(), before)

    def test_reimporting_an_export_changes_nothing(self):
        self.job.model_id = self.model
        before = self.counts()
        exported = self.env['equipment.model.import.wizard']._export_workbook()
        wizard = self.env['equipment.model.import.wizard'].create({'file': base64.b64encode(exported)})
        wizard.action_preview()
        self.assertTrue(wizard.line_ids)
        self.assertEqual({line.status for line in wizard.line_ids}, {'unchanged'})
        self.assertEqual(self.counts(), before)

    def test_export_lists_models_with_their_jobs(self):
        self.job.model_id = self.model
        rows = self.env['equipment.model.import.wizard']._export_rows()
        self.assertIn(['Test Group 01', 'TS100', 'TS100-A', '', 'TS100-001'], rows)

    def test_moves_model_and_family(self):
        group_2 = self.env['equipment.model.category'].create({'name': 'Test Group 02'})
        wizard = self.preview([['Test Group 02', 'TS100', 'TS100-A', '', '']])
        self.assertEqual(self.lines(wizard), [(2, 'update')])
        self.assertIn('moved to Group Test Group 02', wizard.line_ids.message)
        wizard.action_apply()
        self.assertEqual(self.family.category_id, group_2)

    def test_parent_may_come_later_in_the_file(self):
        wizard = self.preview([
            ['', '', 'TS100-A-2', 'TS100-B', ''],
            ['Test Group 01', 'TS100', 'TS100-B', '', ''],
        ])
        self.assertEqual(wizard.error_count, 0)
        wizard.action_apply()
        child = self.env['equipment.model'].search([('name', '=', 'TS100-A-2')])
        self.assertEqual(child.parent_id.name, 'TS100-B')

    def test_model_without_family_takes_its_parents(self):
        wizard = self.preview([['', '', 'TS100-A-3', 'TS100-A', '']])
        wizard.action_apply()
        child = self.env['equipment.model'].search([('name', '=', 'TS100-A-3')])
        self.assertEqual(child.family_id, self.family)

    def test_links_an_existing_job(self):
        wizard = self.preview([['', '', 'TS100-A', '', 'ts100-001']])
        self.assertEqual(self.lines(wizard), [(2, 'update')])
        wizard.action_apply()
        self.assertEqual(self.job.model_id, self.model)

    def test_never_creates_jobs(self):
        wizard = self.preview([['', '', 'TS100-A', '', 'TS100-999']])
        self.assertEqual(self.lines(wizard), [(2, 'error')])
        self.assertIn('does not exist', wizard.line_ids.message)
        self.assertFalse(self.env['project.project'].search([('name', '=', 'TS100-999')]))

    def test_errors_are_explained_per_row_and_block_apply(self):
        wizard = self.preview([
            ['', 'Brand New Family', '', '', ''],
            ['', '', 'TS100-A', 'Nowhere', ''],
            ['', '', '', '', 'TS100-001'],
            ['Test Group 01', 'TS100', 'TS100-C', '', ''],
        ])
        self.assertEqual(self.lines(wizard), [(2, 'error'), (3, 'error'), (4, 'error'), (5, 'create')])
        messages = wizard.line_ids.mapped('message')
        self.assertIn('needs a Group', messages[0])
        self.assertIn('does not exist', messages[1])
        self.assertIn('needs a Model', messages[2])
        with self.assertRaises(UserError):
            wizard.action_apply()
        self.assertFalse(self.env['equipment.model'].search([('name', '=', 'TS100-C')]))

    def test_conflicting_rows_for_one_model(self):
        self.env['equipment.model.family'].create({'name': 'TS300', 'category_id': self.group.id})
        wizard = self.preview([
            ['Test Group 01', 'TS100', 'TS100-D', '', ''],
            ['Test Group 01', 'TS300', 'TS100-D', '', ''],
        ])
        self.assertEqual(self.lines(wizard), [(2, 'create'), (3, 'error')])

    def test_a_model_on_several_rows_with_empty_cells_is_no_conflict(self):
        self.job.model_id = False
        wizard = self.preview([
            ['Test Group 01', 'TS100', 'TS100-A', '', ''],
            ['', '', 'TS100-A', '', 'TS100-001'],
        ])
        self.assertEqual(wizard.error_count, 0)
        self.assertEqual(self.lines(wizard), [(2, 'unchanged'), (3, 'update')])

    def test_a_parent_loop_is_an_error_not_a_crash(self):
        child = self.env['equipment.model'].create({'name': 'TS100-A-4', 'parent_id': self.model.id})
        wizard = self.preview([['', '', 'TS100-A', child.name, '']])
        self.assertEqual(self.lines(wizard), [(2, 'error')])

    def test_empty_cells_change_nothing(self):
        self.model.parent_id = self.env['equipment.model'].create({'name': 'TS100-BASE', 'family_id': self.family.id})
        wizard = self.preview([['', '', 'TS100-A', '', '']])
        self.assertEqual(self.lines(wizard), [(2, 'unchanged')])

    def test_only_managers_import(self):
        wizard = self.wizard([['Test Group 01', 'TS100', 'TS100-A', '', '']])
        for groups in ((), ('equipment_model.group_equipment_model_user',)):
            user = self._create_user(*groups)
            with self.assertRaises(AccessError):
                self.env['equipment.model.import.wizard'].with_user(user).create({'file': wizard.file})
            # Past the access rights, the import itself still refuses.
            with self.assertRaisesRegex(AccessError, 'Only Equipment Model Managers'):
                wizard.with_user(user).sudo().action_preview()
            with self.assertRaisesRegex(AccessError, 'Only Equipment Model Managers'):
                wizard.with_user(user).sudo().action_apply()

    def test_the_import_actions_are_for_managers(self):
        manager_group = self.env.ref('equipment_model.group_equipment_model_manager')
        for xmlid in ('equipment_model.action_equipment_model_import', 'equipment_model.action_equipment_model_export'):
            self.assertEqual(self.env.ref(xmlid).sudo().group_ids, manager_group)

    def test_wrong_layout_is_explained(self):
        wizard = self.wizard([['x']], header=['Name'])
        with self.assertRaisesRegex(UserError, 'Missing: Group'):
            wizard.action_preview()

    def test_not_an_excel_file(self):
        wizard = self.env['equipment.model.import.wizard'].create({'file': base64.b64encode(b'not excel')})
        with self.assertRaisesRegex(UserError, 'not an Excel'):
            wizard.action_preview()

    def test_numbers_read_as_plain_names(self):
        wizard = self.preview([['Test Group 01', 'TS100', 245.0, '', '']])
        self.assertEqual(wizard.line_ids.model_name, '245')
