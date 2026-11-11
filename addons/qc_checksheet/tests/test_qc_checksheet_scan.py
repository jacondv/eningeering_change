import io
import os
from datetime import timedelta

from odoo import fields, http
from odoo.exceptions import AccessError, UserError
from odoo.tests.common import HttpCase, new_test_user, tagged

from ..models import qc_scan_files
from .common import QcChecksheetCase


def _jpeg(width, height, quality=95):
    from PIL import Image
    out = io.BytesIO()
    Image.frombytes('RGB', (width, height), os.urandom(width * height * 3)).save(out, 'JPEG', quality=quality)
    return out.getvalue()


def _png(width, height):
    from PIL import Image
    out = io.BytesIO()
    Image.frombytes('RGB', (width, height), os.urandom(width * height * 3)).save(out, 'PNG')
    return out.getvalue()


def _pdf(pages=1, picture=None):
    """A PDF, with a picture of the given bytes on each page when there is one."""
    pymupdf = qc_scan_files.pymupdf
    document = pymupdf.open()
    for number in range(pages):
        page = document.new_page()
        page.insert_text((72, 72), f'Page {number + 1}')
        if picture:
            page.insert_image(page.rect, stream=picture)
    return document.tobytes()


@tagged('post_install', '-at_install')
class TestQcChecksheetScan(QcChecksheetCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.author = new_test_user(
            cls.env, login='qc_scan_author', groups='base.group_user,qc_checksheet.group_qc_author')
        cls.approver = new_test_user(
            cls.env, login='qc_scan_approver', groups='base.group_user,qc_checksheet.group_qc_approver')
        cls.admin = new_test_user(
            cls.env, login='qc_scan_admin', groups='base.group_user,qc_checksheet.group_qc_admin')
        cls.viewer = new_test_user(cls.env, login='qc_scan_viewer', groups='base.group_user')
        cls.type_panel.required = False
        cls.pdf = _pdf()

    # Helpers

    def _released(self, model=None):
        sheet = self._create_checksheet(model=model or self.model_za90).with_user(self.author)
        self._create_content(sheet)
        sheet.action_submit()
        sheet.with_user(self.approver).action_approve()
        return sheet

    def _new_revision(self, sheet):
        rev = sheet.browse(sheet.with_user(self.author).action_create_revision('Change')['res_id'])
        rev.with_user(self.author).action_submit()
        rev.with_user(self.approver).action_approve()
        return rev

    def _job_sheet(self, job=None):
        job = job or self._create_job()
        JobSheet = self.env['qc.job.checksheet']
        return JobSheet.browse(JobSheet.job_print(job.id, [self.type_general.id]))

    def _upload(self, job_sheet, user=None, files=None, date='today', **kwargs):
        return job_sheet.with_user(user or self.author).scan_upload(
            files or [('signed.pdf', self.pdf)], fields.Date.today() if date == 'today' else date, **kwargs)

    def _request(self, job_sheet, revision=None):
        return self.env['qc.job.checksheet.change'].browse(
            job_sheet.with_user(self.author).action_request_change('Needs it', revision and revision.id))

    # Uploading

    def test_an_author_uploads_a_scan(self):
        self._released()
        job_sheet = self._job_sheet()
        self.assertEqual(job_sheet.inspection_state, 'awaiting')
        scan = self.env['qc.job.checksheet.scan'].browse(self._upload(
            job_sheet, files=[('page1.pdf', self.pdf), ('page2.jpg', _jpeg(60, 60))],
            date=fields.Date.today() - timedelta(days=2), note=' Checked by Binh '))
        self.assertEqual(scan.job_sheet_id, job_sheet)
        self.assertEqual(scan.checksheet_id, job_sheet.checksheet_id)
        self.assertEqual((scan.revision, scan.file_count, scan.note), (1, 2, 'Checked by Binh'))
        self.assertEqual(scan.uploaded_by_id, self.author)
        self.assertEqual(scan.attachment_ids.mapped('name'), ['page1.pdf', 'page2.jpg'])
        self.assertEqual(sorted(scan.attachment_ids.mapped('mimetype')), ['application/pdf', 'image/jpeg'])
        self.assertEqual(scan.total_size, sum(scan.attachment_ids.mapped('file_size')))
        # The sheet now counts as inspected, on the day the scan says.
        self.assertEqual((job_sheet.inspection_state, job_sheet.check_date), ('scanned', fields.Date.today() - timedelta(days=2)))
        self.assertIn('Scan of Rev 1 uploaded', job_sheet.message_ids[0].body)

    def test_the_check_date_is_that_of_the_latest_scan(self):
        self._released()
        job_sheet = self._job_sheet()
        today = fields.Date.today()
        self._upload(job_sheet, date=today - timedelta(days=5))
        self._upload(job_sheet, date=today - timedelta(days=1))
        self.assertEqual(job_sheet.check_date, today - timedelta(days=1))
        self.assertEqual(job_sheet.scan_count, 2)

    def test_only_someone_who_can_author_uploads(self):
        self._released()
        job_sheet = self._job_sheet()
        with self.assertRaises(AccessError):
            self._upload(job_sheet, user=self.viewer)
        with self.assertRaises(AccessError):
            job_sheet.with_user(self.viewer).scan_estimate([('a.pdf', self.pdf)])
        self.assertEqual(job_sheet.inspection_state, 'awaiting')

    def test_the_upload_is_refused_without_a_date_a_file_or_with_too_many(self):
        self._released()
        job_sheet = self._job_sheet()
        with self.assertRaisesRegex(UserError, 'Check Date'):
            self._upload(job_sheet, date=False)
        with self.assertRaisesRegex(UserError, 'future'):
            self._upload(job_sheet, date=fields.Date.today() + timedelta(days=1))
        with self.assertRaisesRegex(UserError, 'at least one file'):
            job_sheet.with_user(self.author).scan_upload([], fields.Date.today())
        with self.assertRaisesRegex(UserError, 'At most'):
            job_sheet.with_user(self.author).scan_upload(
                [(f'p{i}.pdf', self.pdf) for i in range(qc_scan_files.MAX_FILES + 1)], fields.Date.today())
        self.assertFalse(job_sheet.scan_ids)

    def test_only_pdf_jpg_and_png_under_25_mb_are_accepted(self):
        self._released()
        job_sheet = self._job_sheet()
        for name, data, message in (
                ('notes.txt', b'hello', 'not a PDF, JPG or PNG'),
                ('fake.pdf', b'this is not a pdf', 'not a PDF, JPG or PNG'),
                ('wrong.png', self.pdf, 'not a PDF, JPG or PNG'),
                ('empty.pdf', b'', 'empty'),
                ('huge.pdf', b'%PDF-' + b'0' * qc_scan_files.MAX_FILE_SIZE, 'over the 25.0 MB')):
            with self.assertRaisesRegex(UserError, message):
                self._upload(job_sheet, files=[(name, data)])
        for name, data in (('a.JPG', _jpeg(40, 40)), ('b.jpeg', _jpeg(40, 40)), ('c.png', _png(40, 40)), ('d.pdf', self.pdf)):
            self._upload(job_sheet, files=[(name, data)])
        self.assertEqual(job_sheet.scan_count, 4)

    # Making a scan smaller

    def test_a_big_scan_pdf_is_made_much_smaller_and_the_estimate_says_so(self):
        self._released()
        job_sheet = self._job_sheet()
        big = _pdf(pages=2, picture=_jpeg(2000, 2829))
        [estimate] = job_sheet.with_user(self.author).scan_estimate([('scan.pdf', big)])
        self.assertEqual((estimate['name'], estimate['size']), ('scan.pdf', len(big)))
        standard, strong = estimate['standard'], estimate['strong']
        self.assertTrue(standard['reduced'] and strong['reduced'])
        self.assertLess(standard['estimated_size'], len(big) * 0.6)
        self.assertLess(strong['estimated_size'], standard['estimated_size'])
        # Nothing is stored by an estimate.
        self.assertFalse(job_sheet.scan_ids)
        # Reducing at upload stores what the estimate promised, and it is still a readable PDF.
        for level, expected in (('standard', standard), ('strong', strong)):
            scan = self.env['qc.job.checksheet.scan'].browse(self._upload(job_sheet, files=[('scan.pdf', big)], level=level))
            stored = scan.attachment_ids
            self.assertEqual(stored.file_size, expected['estimated_size'], level)
            self.assertEqual(qc_scan_files.pymupdf.open(stream=stored.raw, filetype='pdf').page_count, 2)
        self.assertIn('reduced from', job_sheet.message_ids[0].body)

    def test_the_levels_bring_pictures_to_their_resolution_not_only_by_halves(self):
        """A 240 dpi scan has to come down to 200 (or 110), not just be halved or left alone."""
        pymupdf = qc_scan_files.pymupdf
        sharp = _pdf(pages=1, picture=_jpeg(2000, 2829, quality=85))   # A4 at about 242 dpi

        def picture_size(data):
            document = pymupdf.open(stream=data, filetype='pdf')
            info = document.extract_image(document[0].get_images(full=True)[0][0])
            return info['width'], info['height']

        self.assertEqual(picture_size(sharp), (2000, 2829))
        standard = qc_scan_files.compress('a.pdf', sharp, 'standard')
        strong = qc_scan_files.compress('a.pdf', sharp, 'strong')
        for result, dpi in ((standard, 200), (strong, 110)):
            width, _height = picture_size(result['data'])
            self.assertAlmostEqual(width / (595 / 72), dpi, delta=3)
            self.assertLess(result['size'], len(sharp) * 0.8)
        # Standard keeps the colour; Strong is grey.
        for result, colorspace in ((standard, 3), (strong, 1)):
            document = pymupdf.open(stream=result['data'], filetype='pdf')
            self.assertEqual(document.extract_image(document[0].get_images(full=True)[0][0])['colorspace'], colorspace)

    def test_a_scan_already_at_200_dpi_is_not_resampled_by_standard_only_recompressed(self):
        pymupdf = qc_scan_files.pymupdf
        at_200 = _pdf(pages=1, picture=_jpeg(1654, 2339, quality=90))   # A4 at 200 dpi
        result = qc_scan_files.compress('a.pdf', at_200, 'standard')
        document = pymupdf.open(stream=result['data'], filetype='pdf')
        self.assertEqual(document.extract_image(document[0].get_images(full=True)[0][0])['width'], 1654)
        self.assertLessEqual(result['size'], len(at_200))
        # The same scan at Strong does come down to 110 dpi.
        strong = qc_scan_files.compress('a.pdf', at_200, 'strong')
        document = pymupdf.open(stream=strong['data'], filetype='pdf')
        self.assertLess(document.extract_image(document[0].get_images(full=True)[0][0])['width'], 1000)

    def test_a_picture_already_sharp_enough_is_only_recompressed_never_enlarged(self):
        low = _pdf(pages=1, picture=_jpeg(620, 877, quality=90))   # A4 at about 75 dpi
        result = qc_scan_files.compress('low.pdf', low, 'standard')
        self.assertLessEqual(result['size'], len(low))
        document = qc_scan_files.pymupdf.open(stream=result['data'], filetype='pdf')
        self.assertEqual(document.extract_image(document[0].get_images(full=True)[0][0])['width'], 620)

    def test_a_big_photo_is_made_smaller_and_a_png_becomes_a_jpg(self):
        self._released()
        job_sheet = self._job_sheet()
        photo = _jpeg(3200, 4200, quality=95)
        screenshot = _png(1400, 1000)
        by_name = {item['name']: item for item in job_sheet.with_user(self.author).scan_estimate(
            [('photo.jpg', photo), ('shot.png', screenshot)])}
        self.assertLess(by_name['photo.jpg']['standard']['estimated_size'], len(photo) * 0.5)
        self.assertLess(by_name['photo.jpg']['strong']['estimated_size'], by_name['photo.jpg']['standard']['estimated_size'])
        shot = by_name['shot.png']['standard']
        self.assertEqual(shot['estimated_name'], 'shot.jpg')
        self.assertLess(shot['estimated_size'], len(screenshot))
        scan = self.env['qc.job.checksheet.scan'].browse(self._upload(
            job_sheet, files=[('shot.png', screenshot)], level='standard'))
        self.assertEqual((scan.attachment_ids.name, scan.attachment_ids.mimetype), ('shot.jpg', 'image/jpeg'))

    def test_reducing_never_makes_a_file_bigger(self):
        self._released()
        job_sheet = self._job_sheet()
        from PIL import Image
        solid = io.BytesIO()
        Image.new('RGB', (12, 12), (200, 30, 30)).save(solid, 'JPEG', quality=1)
        for name, data in (('solid.jpg', solid.getvalue()), ('plain.pdf', self.pdf), ('tiny.jpg', _jpeg(30, 30, quality=40))):
            [estimate] = job_sheet.with_user(self.author).scan_estimate([(name, data)])
            for level in ('standard', 'strong'):
                item = estimate[level]
                self.assertLessEqual(item['estimated_size'], len(data), (name, level))
                self.assertEqual(item['reduced'], item['estimated_size'] < len(data), (name, level))
                scan = self.env['qc.job.checksheet.scan'].browse(self._upload(job_sheet, files=[(name, data)], level=level))
                self.assertEqual(scan.attachment_ids.file_size, item['estimated_size'], (name, level))
                if not item['reduced']:
                    self.assertEqual((scan.attachment_ids.name, scan.attachment_ids.raw), (name, data), (name, level))

    def test_an_unknown_way_of_reducing_is_refused(self):
        self._released()
        job_sheet = self._job_sheet()
        with self.assertRaisesRegex(UserError, 'Unknown way'):
            self._upload(job_sheet, level='extreme')

    def test_a_password_protected_pdf_cannot_be_reduced(self):
        self._released()
        job_sheet = self._job_sheet()
        document = qc_scan_files.pymupdf.open()
        document.new_page()
        locked = document.tobytes(encryption=qc_scan_files.pymupdf.PDF_ENCRYPT_AES_256, user_pw='secret', owner_pw='secret')
        with self.assertRaisesRegex(UserError, 'password'):
            job_sheet.with_user(self.author).scan_estimate([('locked.pdf', locked)])

    # Going straight from a list to the place where it is done

    def test_a_list_row_and_its_upload_button_open_the_job_page_at_that_sheet(self):
        self._released()
        job_sheet = self._job_sheet()
        for action in (job_sheet.with_user(self.viewer).action_open_job_page(),
                       job_sheet.with_user(self.author).action_upload_scan()):
            self.assertEqual((action['type'], action['tag']), ('ir.actions.client', 'qc_checksheet.job'))
            self.assertEqual(action['context']['active_id'], job_sheet.job_id.id)
            self.assertEqual(action['context']['focus_type_id'], job_sheet.type_id.id)
        self.assertFalse(job_sheet.with_user(self.viewer).action_open_job_page()['context']['focus_upload'])
        self.assertTrue(job_sheet.with_user(self.author).action_upload_scan()['context']['focus_upload'])
        with self.assertRaises(AccessError):
            job_sheet.with_user(self.viewer).action_upload_scan()

    def test_the_dashboard_rows_of_waiting_changes_name_the_type_to_show(self):
        rev0 = self._released()
        job_sheet = self._job_sheet()
        self._new_revision(rev0)
        self._request(job_sheet)
        data = self.env['qc.checksheet'].with_user(self.viewer).get_dashboard_data(
            [('model_id', '=', job_sheet.model_id.id)])
        [row] = data['rev_changes']['items']
        self.assertEqual((row['job_id'], row['type_id']), (job_sheet.job_id.id, job_sheet.type_id.id))

    def test_human_size(self):
        self.assertEqual(qc_scan_files.human_size(900), '900 B')
        self.assertEqual(qc_scan_files.human_size(1536), '1.5 KB')
        self.assertEqual(qc_scan_files.human_size(25 * 1024 * 1024), '25.0 MB')

    # Deleting

    def test_only_a_qc_administrator_deletes_a_scan(self):
        self._released()
        job_sheet = self._job_sheet()
        scan = self.env['qc.job.checksheet.scan'].browse(self._upload(job_sheet))
        attachment = scan.attachment_ids
        for user in (self.viewer, self.author, self.approver):
            with self.assertRaises(AccessError):
                scan.with_user(user).unlink()
        with self.assertRaises(AccessError):
            scan.with_user(self.author).write({'note': 'edited'})
        scan.with_user(self.admin).unlink()
        self.assertFalse(scan.exists())
        self.assertFalse(attachment.exists())
        self.assertEqual(job_sheet.inspection_state, 'awaiting')
        self.assertIn('deleted by %s' % self.admin.name, job_sheet.message_ids[0].body)

    def test_deleting_the_latest_scan_takes_the_check_date_back_to_the_one_before(self):
        self._released()
        job_sheet = self._job_sheet()
        today = fields.Date.today()
        first = self.env['qc.job.checksheet.scan'].browse(self._upload(job_sheet, date=today - timedelta(days=5)))
        last = self.env['qc.job.checksheet.scan'].browse(self._upload(job_sheet, date=today - timedelta(days=1)))
        last.with_user(self.admin).unlink()
        self.assertEqual(job_sheet.check_date, today - timedelta(days=5))
        first.with_user(self.admin).unlink()
        self.assertFalse(job_sheet.check_date)

    # Re-inspection after a change of Revision

    def test_a_change_after_a_scan_needs_the_approvers_word_on_re_inspection(self):
        rev0 = self._released()
        job_sheet = self._job_sheet()
        self._upload(job_sheet)
        rev1 = self._new_revision(rev0)
        request = self._request(job_sheet)
        self.assertTrue(request.has_scan)
        with self.assertRaisesRegex(UserError, 'already has a scan'):
            request.with_user(self.approver).action_approve()
        with self.assertRaisesRegex(UserError, 'why no new inspection'):
            request.with_user(self.approver).action_approve('skipped', ' ')
        self.assertEqual(request.state, 'pending')
        request.with_user(self.approver).action_approve('required')
        self.assertEqual((request.state, request.reinspection), ('approved', 'required'))
        self.assertEqual(job_sheet.checksheet_id, rev1)
        self.assertEqual(job_sheet.inspection_state, 'reinspection')
        self.assertIn('Re-inspection is required', job_sheet.message_ids[0].body)
        # A scan made on the new Revision settles it.
        self._upload(job_sheet)
        self.assertEqual(job_sheet.inspection_state, 'scanned')

    def test_skipping_re_inspection_keeps_the_earlier_scan_for_that_revision_only(self):
        rev0 = self._released()
        job_sheet = self._job_sheet()
        self._upload(job_sheet)
        rev1 = self._new_revision(rev0)
        rev2 = self._new_revision(rev1)
        request = self._request(job_sheet, rev1)
        request.with_user(self.approver).action_approve('skipped', 'Rev 1 only corrects a typo')
        self.assertEqual((request.reinspection, request.reinspection_reason), ('skipped', 'Rev 1 only corrects a typo'))
        self.assertEqual((job_sheet.checksheet_id, job_sheet.inspection_state), (rev1, 'scanned'))
        self.assertEqual(job_sheet.reinspection_waived_id, rev1)
        self.assertIn('earlier scan still counts', job_sheet.message_ids[0].body)
        # Another Revision after it is not covered by the skip.
        self._request(job_sheet, rev2).with_user(self.approver).action_approve('required')
        self.assertEqual((job_sheet.inspection_state, job_sheet.reinspection_waived_id.id), ('reinspection', False))
        # Back to the Revision that was scanned: it is inspected again by definition.
        self._request(job_sheet, rev0).with_user(self.approver).action_approve('required')
        self.assertEqual(job_sheet.inspection_state, 'scanned')

    def test_a_change_without_a_scan_needs_no_decision(self):
        rev0 = self._released()
        job_sheet = self._job_sheet()
        rev1 = self._new_revision(rev0)
        request = self._request(job_sheet)
        self.assertFalse(request.has_scan)
        request.with_user(self.approver).action_approve()
        self.assertEqual((job_sheet.checksheet_id, request.reinspection, job_sheet.inspection_state), (rev1, False, 'awaiting'))

    def test_the_approve_wizard_passes_the_decision(self):
        rev0 = self._released()
        job_sheet = self._job_sheet()
        other = self._job_sheet()
        self._upload(job_sheet)
        self._new_revision(rev0)
        request = self._request(job_sheet)
        action = request.with_user(self.approver).action_open_approve()
        self.assertEqual(action['res_model'], 'qc.job.change.approve.wizard')
        wizard = self.env['qc.job.change.approve.wizard'].with_user(self.approver).create(
            {'change_id': request.id, 'decision': 'skipped', 'reason': 'Typo'})
        self.assertIn('Rev 1', wizard.scan_summary)
        wizard.action_approve()
        self.assertEqual((request.state, request.reinspection, job_sheet.inspection_state), ('approved', 'skipped', 'scanned'))
        # Without a scan the button approves at once.
        second = self._request(other)
        self.assertTrue(second.with_user(self.approver).action_open_approve())
        self.assertEqual(second.state, 'approved')

    # The Job QC page and the Dashboard

    def test_the_job_page_shows_the_inspection_and_its_scans(self):
        rev0 = self._released()
        job = self._create_job()
        job_sheet = self._job_sheet(job)
        overview = self.env['qc.job.checksheet'].with_user(self.author).job_overview(job.id)
        row = next(r for r in overview['rows'] if r['type_id'] == self.type_general.id)
        self.assertEqual((row['inspection']['state'], row['inspection']['scans'], overview['scanned']), ('awaiting', [], 0))
        self.assertTrue(row['inspection']['can_upload'])
        self.assertFalse(row['inspection']['can_delete'])
        self._upload(job_sheet, files=[('a.pdf', self.pdf), ('b.png', _png(40, 40))], note='All good')
        overview = self.env['qc.job.checksheet'].with_user(self.admin).job_overview(job.id)
        row = next(r for r in overview['rows'] if r['type_id'] == self.type_general.id)
        self.assertEqual((row['inspection']['state'], overview['scanned']), ('scanned', 1))
        self.assertTrue(row['inspection']['can_delete'])
        self.assertFalse(self.env['qc.job.checksheet'].with_user(self.viewer).job_overview(job.id)['rows'][0]['inspection']['can_upload'])
        [scan] = row['inspection']['scans']
        self.assertEqual((scan['revision'], scan['note'], scan['covers_current'], len(scan['files'])), (1, 'All good', True, 2))
        self.assertEqual([f['name'] for f in scan['files']], ['a.pdf', 'b.png'])
        self.assertTrue(scan['files'][0]['url'].startswith('/web/content/'))
        # A pending change of a scanned Job says so, so the Approver is asked.
        self._new_revision(rev0)
        self._request(job_sheet)
        row = next(r for r in self.env['qc.job.checksheet'].with_user(self.approver).job_overview(job.id)['rows']
                   if r['type_id'] == self.type_general.id)
        self.assertTrue(row['pending']['has_scan'])

    def test_a_viewer_can_read_a_scan_but_not_the_files_of_a_job_they_cannot_see_changed(self):
        self._released()
        job_sheet = self._job_sheet()
        scan = self.env['qc.job.checksheet.scan'].browse(self._upload(job_sheet))
        as_viewer = scan.with_user(self.viewer)
        self.assertEqual(as_viewer.attachment_ids.name, 'signed.pdf')
        self.assertTrue(as_viewer.attachment_ids.raw)

    def test_the_dashboard_counts_sheets_awaiting_a_scan_and_jobs_to_inspect_again(self):
        Sheet = self.env['qc.checksheet'].with_user(self.viewer)
        model = self._create_model()
        rev0 = self._released(model)
        before = Sheet.get_dashboard_data([('model_id', '=', model.id)])['inspections']
        self.assertEqual(before, {'awaiting': 0, 'reinspection': 0})
        waiting, scanned, again = (self._job_sheet(self._create_job(model=model)) for _i in range(3))
        self._upload(scanned)
        self._upload(again)
        self._new_revision(rev0)
        self._request(again).with_user(self.approver).action_approve('required')
        counts = Sheet.get_dashboard_data([('model_id', '=', model.id)])['inspections']
        self.assertEqual(counts, {'awaiting': 1, 'reinspection': 1})
        # A Job that is no longer open is left out.
        waiting.job_id.last_update_status = 'eol'
        self.assertEqual(Sheet.get_dashboard_data([('model_id', '=', model.id)])['inspections']['awaiting'], 0)
        # And a search that names another Model leaves these out.
        self.assertEqual(Sheet.get_dashboard_data([('model_id', '=', self._create_model().id)])['inspections'],
                         {'awaiting': 0, 'reinspection': 0})


@tagged('post_install', '-at_install')
class TestQcChecksheetScanRoutes(HttpCase):
    """The page sends the files as a multipart request, with the CSRF token, and reads JSON back."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.model = cls.env['equipment.model'].create({'name': 'ROUTE-TEST'})
        cls.type = cls.env.ref('qc_checksheet.checksheet_type_general')
        sheet = cls.env['qc.checksheet'].create({'name': 'Route', 'type_id': cls.type.id, 'model_id': cls.model.id})
        cls.env['qc.checksheet.group'].create({
            'checksheet_id': sheet.id, 'name': 'G', 'item_ids': [(0, 0, {'description': 'Check'})]})
        sheet.write({'state': 'released'})
        cls.job = cls.env['project.project'].create({'name': 'J-ROUTE-1', 'model_id': cls.model.id})
        JobSheet = cls.env['qc.job.checksheet']
        cls.job_sheet = JobSheet.browse(JobSheet.job_print(cls.job.id, [cls.type.id]))
        cls.author = new_test_user(
            cls.env, login='qc_route_author', groups='base.group_user,qc_checksheet.group_qc_author')
        cls.viewer = new_test_user(cls.env, login='qc_route_viewer', groups='base.group_user')
        cls.pdf = _pdf()

    def _post(self, route, files, **data):
        data['csrf_token'] = http.Request.csrf_token(self)
        return self.url_open(route, data=data, files=[('ufile', (name, io.BytesIO(content))) for name, content in files])

    def test_upload_stores_the_scan_and_answers_with_its_id(self):
        self.authenticate('qc_route_author', 'qc_route_author')
        response = self._post(
            '/qc_checksheet/scan/upload', [('signed.pdf', self.pdf), ('side.jpg', _jpeg(50, 50))],
            job_sheet_id=self.job_sheet.id, check_date=str(fields.Date.today()), note='From the form', reduce='0')
        self.assertEqual(response.status_code, 200, response.text)
        scan = self.env['qc.job.checksheet.scan'].browse(response.json()['scan_id'])
        self.assertEqual((scan.job_sheet_id, scan.file_count, scan.note), (self.job_sheet, 2, 'From the form'))
        self.assertEqual(self.job_sheet.inspection_state, 'scanned')

    def test_the_estimate_route_stores_nothing(self):
        self.authenticate('qc_route_author', 'qc_route_author')
        big = _pdf(pages=1, picture=_jpeg(2000, 2829))
        response = self._post('/qc_checksheet/scan/estimate', [('scan.pdf', big)])
        self.assertEqual(response.status_code, 200, response.text)
        [item] = response.json()['files']
        self.assertEqual((item['name'], item['size']), ('scan.pdf', len(big)))
        self.assertTrue(item['standard']['reduced'])
        self.assertLess(item['strong']['estimated_size'], item['standard']['estimated_size'])
        self.assertLess(item['standard']['estimated_size'], item['size'])
        self.assertFalse(self.job_sheet.scan_ids)

    def test_upload_reduces_at_the_level_asked_for(self):
        self.authenticate('qc_route_author', 'qc_route_author')
        big = _pdf(pages=1, picture=_jpeg(2000, 2829))
        for reduce, smaller in (('none', False), ('standard', True), ('strong', True), ('1', True)):
            response = self._post(
                '/qc_checksheet/scan/upload', [('scan.pdf', big)],
                job_sheet_id=self.job_sheet.id, check_date=str(fields.Date.today()), reduce=reduce)
            self.assertEqual(response.status_code, 200, (reduce, response.text))
            size = self.env['qc.job.checksheet.scan'].browse(response.json()['scan_id']).attachment_ids.file_size
            self.assertEqual(size < len(big), smaller, reduce)

    def test_a_refused_upload_answers_with_the_reason_as_json(self):
        self.authenticate('qc_route_author', 'qc_route_author')
        response = self._post(
            '/qc_checksheet/scan/upload', [('notes.txt', b'hello')],
            job_sheet_id=self.job_sheet.id, check_date=str(fields.Date.today()), reduce='0')
        self.assertEqual(response.status_code, 400)
        self.assertIn('not a PDF, JPG or PNG', response.json()['error'])
        self.assertFalse(self.job_sheet.scan_ids)

    def test_a_file_over_the_limit_is_refused_before_it_is_stored(self):
        self.authenticate('qc_route_author', 'qc_route_author')
        self.env['ir.config_parameter'].sudo().set_param('qc_checksheet.scan_max_file_mb', '1')
        self.addCleanup(self.registry.clear_all_caches)
        response = self._post(
            '/qc_checksheet/scan/upload', [('big.pdf', b'%PDF-' + b'0' * (1024 * 1024 + 10))],
            job_sheet_id=self.job_sheet.id, check_date=str(fields.Date.today()), reduce='0')
        self.assertEqual(response.status_code, 400)
        self.assertIn('over the 1.0 MB', response.json()['error'])
        self.assertFalse(self.job_sheet.scan_ids)

    def test_someone_who_cannot_author_is_refused(self):
        self.authenticate('qc_route_viewer', 'qc_route_viewer')
        response = self._post(
            '/qc_checksheet/scan/upload', [('signed.pdf', self.pdf)],
            job_sheet_id=self.job_sheet.id, check_date=str(fields.Date.today()), reduce='0')
        self.assertEqual(response.status_code, 400)
        self.assertIn('access rights', response.json()['error'])
        self.assertFalse(self.job_sheet.scan_ids)

    def test_a_request_without_the_csrf_token_is_refused(self):
        self.authenticate('qc_route_author', 'qc_route_author')
        response = self.url_open(
            '/qc_checksheet/scan/upload', data={'job_sheet_id': self.job_sheet.id, 'check_date': str(fields.Date.today())},
            files=[('ufile', ('signed.pdf', io.BytesIO(self.pdf)))])
        self.assertIn(response.status_code, (400, 403))
        self.assertFalse(self.job_sheet.scan_ids)


@tagged('post_install', '-at_install')
class TestQcChecksheetScanLimits(QcChecksheetCase):
    """The largest scan file is a Setting, 25 MB unless a QC Administrator changes it."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.author = new_test_user(
            cls.env, login='qc_limit_author', groups='base.group_user,qc_checksheet.group_qc_author')
        cls.admin = new_test_user(
            cls.env, login='qc_limit_admin', groups='base.group_user,qc_checksheet.group_qc_admin')
        cls.pdf = _pdf()

    def test_the_default_is_25_mb_and_ten_files(self):
        self.assertEqual(self.env['qc.job.checksheet'].scan_limits(), {'max_file_size': 25 * 1024 * 1024, 'max_files': 10})
        settings = self.env['qc.checksheet.settings'].with_user(self.admin).create({})
        self.assertEqual(settings.scan_max_file_mb, 25)

    def test_an_administrator_changes_it_and_uploads_follow(self):
        # The Setting is a cached system parameter: the rollback after the test must not leave its value behind.
        self.addCleanup(self.env.registry.clear_all_caches)
        settings = self.env['qc.checksheet.settings'].with_user(self.admin).create({'scan_max_file_mb': 1})
        settings.action_save()
        self.assertEqual(self.env['qc.job.checksheet'].scan_limits()['max_file_size'], 1024 * 1024)
        sheet = self._create_checksheet(model=self.model_za90)
        self.env['qc.checksheet.group'].create({
            'checksheet_id': sheet.id, 'name': 'G', 'item_ids': [(0, 0, {'description': 'Check'})]})
        sheet.write({'state': 'released'})
        JobSheet = self.env['qc.job.checksheet']
        job_sheet = JobSheet.browse(JobSheet.job_print(self._create_job().id, [self.type_general.id]))
        with self.assertRaisesRegex(UserError, 'over the 1.0 MB'):
            job_sheet.with_user(self.author).scan_upload(
                [('big.pdf', b'%PDF-' + b'0' * (1024 * 1024))], fields.Date.today())
        job_sheet.with_user(self.author).scan_upload([('ok.pdf', self.pdf)], fields.Date.today())
        # And back up again.
        self.env['qc.checksheet.settings'].with_user(self.admin).create({'scan_max_file_mb': 40}).action_save()
        self.assertEqual(JobSheet.scan_limits()['max_file_size'], 40 * 1024 * 1024)

    def test_the_setting_has_bounds_and_belongs_to_the_administrator(self):
        for megabytes in (0, 201):
            with self.assertRaisesRegex(UserError, 'between 1 and 200'):
                self.env['qc.checksheet.settings'].with_user(self.admin).create({'scan_max_file_mb': megabytes}).action_save()
        with self.assertRaises(AccessError):
            self.env['qc.checksheet.settings'].with_user(self.author).create({'scan_max_file_mb': 30})
