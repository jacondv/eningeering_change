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

    def _sheets(self, **job_vals):
        job = self._create_job(**job_vals)
        general = self._create_checksheet(job=job)
        self._create_content(general)
        hydraulic = self._create_checksheet(self.type_hydraulic, job=job)
        self._create_content(hydraulic)
        return (general | hydraulic).with_user(self.viewer)

    def test_file_name_uses_the_machine_serial(self):
        general, _hydraulic = self._sheets(machine_serial='SN-123')
        self.assertEqual(general.pdf_file_name, 'SN-123-QC-GENERAL CHECK SHEET')

    def test_file_name_falls_back_to_the_job_number_and_drops_unsafe_characters(self):
        sheets = self._sheets(name='J-PRINT-1')
        self.assertEqual(sheets[1].pdf_file_name, 'J-PRINT-1-QC-HYDRAULIC MAINAUX')

    def test_the_pdf_report_uses_that_name(self):
        report = self.env.ref('qc_checksheet.action_report_qc_checksheet')
        self.assertEqual(report.print_report_name, 'object.pdf_file_name')

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

    def test_nothing_selected(self):
        with self.assertRaises(UserError):
            self.env['qc.checksheet'].with_user(self.viewer)._print_files()

    def test_needs_read_access(self):
        sheets = self._sheets()
        outsider = new_test_user(self.env, login='qc_print_outsider', groups='base.group_portal')
        with self.assertRaises(AccessError):
            sheets.with_user(outsider)._print_files()
