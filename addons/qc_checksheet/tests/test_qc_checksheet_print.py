import io
import zipfile

from odoo.exceptions import AccessError, UserError
from odoo.tests.common import new_test_user, tagged

from .common import QcChecksheetCase


@tagged('post_install', '-at_install')
class TestQcChecksheetPrint(QcChecksheetCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.viewer = new_test_user(cls.env, login='qc_print_viewer', groups='base.group_user')
        cls.type_hydraulic = cls.env['qc.checksheet.type'].create({'name': 'Hydraulic: Main/Aux', 'code': 'HY'})
        for checksheet_type in (cls.type_general, cls.type_hydraulic):
            sheet = cls.env['qc.checksheet'].create({
                'name': 'Sheet', 'type_id': checksheet_type.id, 'model_id': cls.model_za90.id})
            cls.env['qc.checksheet.group'].create({
                'checksheet_id': sheet.id, 'name': 'Group', 'item_ids': [(0, 0, {'description': 'Check'})]})
            sheet.write({'state': 'released'})

    def _sheets(self, **job_vals):
        """The Job's General and Hydraulic sheets, printed (so pinned) by the viewer."""
        job = self._create_job(**job_vals)
        JobSheet = self.env['qc.job.checksheet'].with_user(self.viewer)
        return JobSheet.browse(JobSheet.job_print(job.id, [self.type_general.id, self.type_hydraulic.id]))

    def test_file_name_uses_the_machine_serial(self):
        general, _hydraulic = self._sheets(machine_serial='SN-123')
        self.assertEqual(general.pdf_file_name, 'SN-123-QC-GENERAL CHECK SHEET')

    def test_file_name_falls_back_to_the_job_number_and_drops_unsafe_characters(self):
        sheets = self._sheets(name='J-PRINT-1')
        self.assertEqual(sheets[1].pdf_file_name, 'J-PRINT-1-QC-HYDRAULIC MAINAUX')

    def test_a_models_blank_sheet_is_named_after_its_number_and_revision(self):
        sheet = self.env['qc.checksheet'].search([('model_id', '=', self.model_za90.id), ('type_id', '=', self.type_general.id)])
        self.assertEqual(sheet.pdf_file_name, 'QC-GE-ZA90-REV0')

    def test_the_pdf_reports_use_those_names(self):
        for xmlid in ('qc_checksheet.action_report_qc_checksheet', 'qc_checksheet.action_report_qc_job_checksheet'):
            self.assertEqual(self.env.ref(xmlid).print_report_name, 'object.pdf_file_name')

    def test_one_sheet_prints_as_its_own_pdf(self):
        sheets = self._sheets(machine_serial='SN-1')
        name, content, mimetype = sheets[0]._print_files()
        self.assertEqual((name, mimetype), ('SN-1-QC-GENERAL CHECK SHEET.pdf', 'application/pdf'))
        self.assertTrue(content)

    def test_several_sheets_print_one_pdf_each_in_a_zip(self):
        sheets = self._sheets(machine_serial='SN-2')
        name, content, mimetype = sheets._print_files()
        self.assertEqual((name, mimetype), ('SN-2-QC.zip', 'application/zip'))
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            self.assertEqual(archive.namelist(), [
                'SN-2-QC-GENERAL CHECK SHEET.pdf', 'SN-2-QC-HYDRAULIC MAINAUX.pdf'])

    def test_several_sheets_print_combined(self):
        sheets = self._sheets(name='J-PRINT-3')
        name, content, mimetype = sheets._print_files(combined=True)
        self.assertEqual((name, mimetype), ('J-PRINT-3-QC-ALL.pdf', 'application/pdf'))
        self.assertTrue(content)

    def test_two_types_with_one_name_stay_two_files_in_a_zip(self):
        twin = self.env['qc.checksheet.type'].create({'name': 'General Check Sheet', 'code': 'G2'})
        sheet = self.env['qc.checksheet'].create({'name': 'Twin', 'type_id': twin.id, 'model_id': self.model_za90.id})
        self.env['qc.checksheet.group'].create({
            'checksheet_id': sheet.id, 'name': 'Group', 'item_ids': [(0, 0, {'description': 'Check'})]})
        sheet.write({'state': 'released'})
        job = self._create_job(machine_serial='SN-TWIN')
        JobSheet = self.env['qc.job.checksheet'].with_user(self.viewer)
        sheets = JobSheet.browse(JobSheet.job_print(job.id, [self.type_general.id, twin.id]))
        self.assertEqual(len(set(sheets.mapped('pdf_file_name'))), 1)
        _name, content, _mimetype = sheets._print_files()
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            self.assertEqual(
                sorted(archive.namelist()),
                ['SN-TWIN-QC-GENERAL CHECK SHEET (2).pdf', 'SN-TWIN-QC-GENERAL CHECK SHEET.pdf'])

    def test_nothing_selected(self):
        with self.assertRaises(UserError):
            self.env['qc.job.checksheet'].with_user(self.viewer)._print_files()

    def test_needs_read_access(self):
        sheets = self._sheets()
        outsider = new_test_user(self.env, login='qc_print_outsider', groups='base.group_portal')
        with self.assertRaises(AccessError):
            sheets.with_user(outsider)._print_files()
