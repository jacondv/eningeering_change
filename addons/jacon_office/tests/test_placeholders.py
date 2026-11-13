import base64
import io
import json
import re
import zipfile
from datetime import date, datetime
from unittest.mock import MagicMock, patch

from lxml import etree

from odoo.exceptions import AccessError, UserError
from odoo.tools import config
from odoo.tests import HttpCase, TransactionCase, tagged

from odoo.addons.jacon_office.models import office_placeholders
from odoo.addons.onlyoffice_odoo.utils import config_utils, jwt_utils

A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
DOCUMENT_MODULE = 'odoo.addons.jacon_office.models.jacon_office_document'


def paragraph(*runs):
    """A paragraph made of runs, each (text, bold)."""
    return '<a:p>%s</a:p>' % ''.join(
        '<a:r><a:rPr b="%d"/><a:t>%s</a:t></a:r>' % (int(bold), text) for text, bold in runs
    )


@tagged('post_install', '-at_install', 'jacon_office')
class TestPlaceholders(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Document = cls.env['jacon.office.document']
        cls.env['ir.config_parameter'].set_param('onlyoffice_connector.internal_jwt_secret', 'internal-test-secret')
        cls.partner = cls.env['res.partner'].create({'name': 'Acme'})
        cls.manager = cls.env['res.users'].create({
            'name': 'Office Manager', 'login': 'ph_manager',
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id, cls.env.ref('base.group_partner_manager').id,
                cls.env.ref('jacon_office.group_jacon_office_manager').id,
            ])],
        })

    # -- helpers -------------------------------------------------------

    def _pptx(self, paragraphs, master_title=None):
        """A presentation whose only slide holds these paragraphs (xml strings)."""
        source = self.Document._blank_file('pptx')
        slide = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<p:sld xmlns:a="%s" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
            '<p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/>'
            '<p:sp><p:nvSpPr><p:cNvPr id="2" name="Text"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr/>'
            '<p:txBody><a:bodyPr/>%s</p:txBody></p:sp></p:spTree></p:cSld></p:sld>' % (A, ''.join(paragraphs))
        )
        out = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(source)) as zin, zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename == 'ppt/slides/slide1.xml':
                    data = slide.encode()
                elif item.filename == 'ppt/slideMasters/slideMaster1.xml' and master_title:
                    marker = b'Click to edit Master title style'
                    assert marker in data
                    data = data.replace(marker, master_title.encode())
                zout.writestr(item, data)
        return out.getvalue()

    def _paragraphs(self, content, part='ppt/slides/slide1.xml'):
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            root = etree.fromstring(archive.read(part))
        return [
            ''.join(t.text or '' for t in p.iter('{%s}t' % A)) for p in root.iter('{%s}p' % A)
        ]

    def _runs(self, content):
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            root = etree.fromstring(archive.read('ppt/slides/slide1.xml'))
        return [(t.text, t.getparent().find('{%s}rPr' % A).get('b')) for t in root.iter('{%s}t' % A)]

    def _doc(self, content, **vals):
        values = {
            'name': 'Acme-Spec', 'kind': 'pptx', 'res_model': 'res.partner', 'res_id': self.partner.id,
            'file_content': content,
        }
        values.update(vals)
        return self.Document.create(values)

    def _release(self, doc):
        with patch.object(type(self.Document), '_editor_is_open', lambda rec: False):
            doc.action_submit()
        doc.with_user(self.manager).action_approve()

    # -- the engine ----------------------------------------------------

    def test_a_placeholder_split_over_runs_is_filled_in_the_run_where_it_starts(self):
        content = self._pptx([paragraph(('Rev: ', False), ('{{re', True), ('v}} (draft)', False))])
        filled = office_placeholders.fill(content, 'pptx', {'rev': 3})
        self.assertEqual(self._paragraphs(filled), ['Rev: 3 (draft)'])
        self.assertEqual(self._runs(filled), [('Rev: ', '0'), ('3', '1'), (' (draft)', '0')])

    def test_names_ignore_case_and_spaces_and_values_are_escaped(self):
        content = self._pptx([paragraph(('{{ CATEGORY }} by {{Author}} &amp; {{category}}', False))])
        filled = office_placeholders.fill(content, 'pptx', {'category': 'R&D <spec>', 'author': 'Ann'})
        self.assertEqual(self._paragraphs(filled), ['R&D <spec> by Ann & R&D <spec>'])

    def test_an_unknown_placeholder_stays_as_typed(self):
        content = self._pptx([paragraph(('{{rev}} {{bogus}}', False))])
        self.assertEqual(self._paragraphs(office_placeholders.fill(content, 'pptx', {'rev': 2})), ['2 {{bogus}}'])
        self.assertEqual(office_placeholders.tokens_in(content, 'pptx'), {'rev', 'bogus'})

    def test_masters_and_layouts_are_filled_too(self):
        content = self._pptx([paragraph(('plain', False))], master_title='Master {{rev}}')
        filled = office_placeholders.fill(content, 'pptx', {'rev': 7})
        self.assertIn('Master 7', self._paragraphs(filled, 'ppt/slideMasters/slideMaster1.xml'))
        self.assertEqual(office_placeholders.tokens_in(content, 'pptx'), {'rev'})

    def test_a_file_without_placeholders_is_returned_as_it_is(self):
        content = self._pptx([paragraph(('nothing here', False))])
        self.assertIs(office_placeholders.fill(content, 'pptx', {'rev': 1}), content)
        self.assertFalse(office_placeholders.tokens_in(content, 'pptx'))
        # the other parts are copied untouched
        filled = office_placeholders.fill(self._pptx([paragraph(('{{rev}}', False))]), 'pptx', {'rev': 1})
        with zipfile.ZipFile(io.BytesIO(filled)) as archive, zipfile.ZipFile(io.BytesIO(content)) as original:
            self.assertEqual(archive.read('ppt/theme/theme1.xml'), original.read('ppt/theme/theme1.xml'))

    def test_other_kinds_and_broken_files_are_left_alone(self):
        docx = self.Document._blank_file('docx')
        self.assertIs(office_placeholders.fill(docx, 'docx', {'rev': 1}), docx)
        self.assertFalse(office_placeholders.is_supported('docx'))
        self.assertEqual(office_placeholders.tokens_in(b'not a zip', 'pptx'), set())

    # -- the values ----------------------------------------------------

    def test_dates_read_12_aug_2026(self):
        self.assertEqual(self.Document._format_date(date(2026, 8, 12)), '12-Aug-2026')
        self.assertEqual(self.Document._format_date(datetime(2026, 1, 3, 10, 0)), '03-Jan-2026')
        self.assertEqual(self.Document._format_date(False), '')

    def test_the_documents_values(self):
        doc = self._doc(self._pptx([paragraph(('x', False))]), author='Ann', description='About it')
        values = doc._placeholder_values()
        self.assertEqual(
            (values['rev'], values['state']), (1, 'Draft'),
        )
        self.assertEqual((values['released_by'], values['released_date']), ('', ''))
        self.assertNotIn('author', values)  # written into the file once, when the document is made
        self.assertNotIn('date', values)
        self.assertNotIn('name', values)

    def test_the_details_are_written_into_the_file_when_the_document_is_made(self):
        doc = self._doc(self._pptx([paragraph(('{{author}} / {{belongs_to}} / Rev {{rev}}', False))]), author='Ann')
        # the stored file has them already, and keeps the one that follows the workflow
        self.assertEqual(self._paragraphs(doc.attachment_id.raw), ['Ann / Acme / Rev {{rev}}'])
        self.assertEqual(self._paragraphs(doc._download_file()[2]), ['Ann / Acme / Rev 1'])
        doc.write({'author': 'Bob'})
        self.assertEqual(self._paragraphs(doc._download_file()[2]), ['Ann / Acme / Rev 1'])

    def test_the_template_form_guides_the_designer(self):
        template = self.env['jacon.office.template'].create({
            'name': 'Guided deck', 'kind': 'pptx',
            'upload': base64.b64encode(self._pptx([paragraph(('{{rev}} {{author}} {{typo}}', False))])),
            'upload_filename': 'deck.pptx',
        })
        guide = str(template.placeholder_guide)
        for name in office_placeholders.CATALOG:
            self.assertIn('{{%s}}' % name, guide)
        self.assertIn('12-Aug-2026', guide)
        self.assertIn('{{rev}}: OK', template.placeholder_report)
        self.assertIn('{{typo}}: UNKNOWN', template.placeholder_report)
        self.assertNotIn('You can use', template.placeholder_report)
        wizard = self.env['jacon.office.document.create.wizard'].new({'template_id': template.id})
        self.assertEqual(wizard.template_tokens, 'This template fills in: author, rev')
        self.assertFalse(self.env['jacon.office.document.create.wizard'].new({}).template_tokens)

    def test_a_value_of_zero_is_shown_as_zero(self):
        doc = self._doc(self._pptx([paragraph(('Qty {{Partner.Qty}} / {{Partner.None}}', False))]))
        with patch.object(self.env.registry['res.partner'], '_office_placeholders', create=True,
                          new=lambda rec: {'Partner.Qty': 0, 'Partner.None': None}):
            self.assertEqual(self._paragraphs(doc._download_file()[2]), ['Qty 0 / '])

    def test_a_file_that_unpacks_to_far_too_much_is_refused_or_left_alone(self):
        content = self._pptx([paragraph(('{{rev}}', False))])
        with patch.object(office_placeholders, 'MAX_UNPACKED_SIZE', 10):
            self.assertIs(office_placeholders.fill(content, 'pptx', {'rev': 1}), content)
            self.assertEqual(office_placeholders.tokens_in(content, 'pptx'), set())
            with self.assertRaises(UserError):
                self.Document._check_office_file(content, 'pptx')

    def test_the_record_a_document_belongs_to_adds_values(self):
        doc = self._doc(self._pptx([paragraph(('City: {{Partner.City}}', False))]))
        with patch.object(self.env.registry['res.partner'], '_office_placeholders', create=True,
                          new=lambda rec: {'Partner.City': 'Hanoi'}):
            self.assertEqual(self._paragraphs(doc._download_file()[2]), ['City: Hanoi'])

    # -- what is shown -------------------------------------------------

    def test_a_download_fills_the_placeholders_but_the_stored_file_keeps_them(self):
        stored = self._pptx([paragraph(('Spec Rev {{rev}} {{state}}', False))])
        doc = self._doc(stored)
        name, mimetype, content = doc._download_file()
        self.assertEqual(name, 'Acme-Spec.pptx')
        self.assertEqual(self._paragraphs(content), ['Spec Rev 1 Draft'])
        self.assertEqual(doc.attachment_id.raw, stored)

    def test_the_original_download_keeps_the_placeholders_and_can_be_put_back(self):
        doc = self._doc(self._pptx([paragraph(('Rev {{rev}}', False))]))
        name, mimetype, original = doc._download_file(original=True)
        self.assertEqual(self._paragraphs(original), ['Rev {{rev}}'])
        self.assertEqual(self._paragraphs(doc._download_file()[2]), ['Rev 1'])
        changed = self._pptx([paragraph(('Changed in Office, Rev {{rev}}', False))])
        wizard = self.env['jacon.office.document.replace.wizard'].create({
            'document_id': doc.id, 'upload': base64.b64encode(changed), 'upload_filename': 'Acme-Spec.pptx',
        })
        wizard.action_confirm()  # what the dialog does: the file arrives base64 encoded
        self.assertEqual(doc.attachment_id.raw, changed)
        action = doc.action_ask_replace_file()  # the web client needs `views` to open it
        self.assertEqual(action['views'], [(False, 'form')])
        self.assertTrue(doc.action_replace_file(changed, 'Acme-Spec.pptx'))
        self.assertEqual(doc.attachment_id.raw, changed)
        self.assertEqual(self._paragraphs(doc._download_file()[2]), ['Changed in Office, Rev 1'])
        self.assertEqual(doc.pdf_state, 'pending')
        self.assertIn('replaced the file', doc.message_ids[0].body)

    def test_the_file_of_a_draft_is_replaced_by_a_file_of_the_same_type_only(self):
        doc = self._doc(self._pptx([paragraph(('x', False))]))
        before = doc.attachment_id.raw
        with self.assertRaises(UserError):
            doc.action_replace_file(self.Document._blank_file('docx'), 'Other.docx')  # another type
        with self.assertRaises(UserError):
            doc.action_replace_file(b'not an office file', 'Other.pptx')
        self.assertEqual(doc.attachment_id.raw, before)
        self._release(doc)
        with self.assertRaises(AccessError):
            doc.with_user(self.manager).action_replace_file(self._pptx([paragraph(('y', False))]), 'x.pptx')  # released

    def test_each_rev_downloads_with_the_values_it_was_released_with(self):
        doc = self._doc(self._pptx([paragraph(('Rev {{rev}} {{state}} by {{released_by}}', False))]))
        self._release(doc)
        doc.action_new_revision('Change')
        self._release(doc)
        rev1 = doc.version_ids.filtered(lambda v: v.number == 1)
        rev2 = doc.version_ids.filtered(lambda v: v.number == 2)
        self.assertEqual(self._paragraphs(rev1._download_file()[2]), ['Rev 1 Released by Office Manager'])
        self.assertEqual(self._paragraphs(rev2._download_file()[2]), ['Rev 2 Released by Office Manager'])
        # the Rev keeps the placeholders themselves too: a new Rev built on it fills them again
        self.assertEqual(self._paragraphs(rev1.attachment_id.raw), ['Rev {{rev}} {{state}} by {{released_by}}'])

    def test_an_old_rev_is_viewed_as_a_pdf_made_once_with_the_values_it_was_released_with(self):
        doc = self._doc(self._pptx([paragraph(('Rev {{rev}}', False))]))
        self._release(doc)
        doc.action_new_revision('Change')
        self._release(doc)
        rev1 = doc.version_ids.filtered(lambda v: v.number == 1)
        converter = MagicMock(status_code=200)
        converter.json.return_value = {'endConvert': True, 'fileUrl': 'http://onlyoffice/cache/files/output.pdf'}
        download = MagicMock(status_code=200, content=b'%PDF-1.7 fake')
        with patch(DOCUMENT_MODULE + '.requests.post', return_value=converter) as post,                 patch(DOCUMENT_MODULE + '.requests.get', return_value=download):
            action = rev1.with_user(self.manager).action_view_pdf()
            again = rev1.with_user(self.manager).action_view_pdf()
        self.assertEqual(post.call_count, 1)  # the second view reuses the PDF
        body = json.loads(post.call_args.kwargs['data'])
        self.assertEqual(body['key'], 'pdfa-rev-%s' % rev1.id)
        self.assertIn('/jacon_office/rev/%s/filled?oo_security_token=' % rev1.id, body['url'])
        self.assertEqual(action['url'], again['url'])
        self.assertEqual(action['target'], 'new')
        self.assertEqual(rev1.pdf_attachment_id.raw, b'%PDF-1.7 fake')
        # what ONLYOFFICE fetches shows Rev 1 although the document is now at Rev 2
        self.assertEqual(self._paragraphs(rev1._download_file()[2]), ['Rev 1'])
        pdf = rev1.pdf_attachment_id
        rev1.unlink()
        self.assertFalse(pdf.exists())

    def test_the_pdf_follows_the_values_the_file_shows(self):
        doc = self._doc(self._pptx([paragraph(('Rev {{rev}}', False))]))
        key = doc._render_key()
        self.assertNotEqual(key, doc.attachment_id.checksum)
        self.assertEqual(doc._render_key(), key)  # nothing changed
        self._release(doc)
        doc.action_new_revision('Change')
        self.assertNotEqual(doc._render_key(), key)  # Rev 2 is another text

        plain = self._doc(self._pptx([paragraph(('no placeholder', False))]), name='Plain')
        before = plain._render_key()
        self.assertEqual(before, plain.attachment_id.checksum)
        self._release(plain)
        self.assertEqual(plain._render_key(), before)  # a Rev changes nothing in a file that shows none

    def _convert(self, doc):
        """Make the PDF with ONLYOFFICE answering fine; returns the body that was sent to it."""
        converter = MagicMock(status_code=200)
        converter.json.return_value = {'endConvert': True, 'fileUrl': 'http://onlyoffice/cache/files/output.pdf'}
        download = MagicMock(status_code=200, content=b'%PDF-1.7 fake')
        with patch(DOCUMENT_MODULE + '.requests.post', return_value=converter) as post, \
                patch(DOCUMENT_MODULE + '.requests.get', return_value=download):
            self.assertTrue(doc._convert_to_pdf())
        return json.loads(post.call_args.kwargs['data'])

    def test_onlyoffice_fetches_the_filled_file_not_a_stored_copy(self):
        doc = self._doc(self._pptx([paragraph(('Rev {{rev}}', False))]))
        attachments = self.env['ir.attachment'].search_count([])
        body = self._convert(doc)
        self.assertIn('/jacon_office/document/%s/filled?oo_security_token=' % doc.id, body['url'])
        self.assertNotIn('/onlyoffice/file/content/', body['url'])
        self.assertEqual(body['key'], 'pdfa-%s-%s' % (doc.attachment_id.id, doc._render_key()))
        self.assertEqual(self.env['ir.attachment'].search_count([]), attachments + 1)  # only the PDF: no copy kept
        self.assertTrue(doc._pdf_is_current())
        self._release(doc)
        doc.action_new_revision('Change')
        self.assertFalse(doc._pdf_is_current())  # it says Rev 1 and the file now shows Rev 2

    def test_the_token_for_the_filled_file_names_one_document(self):
        doc = self._doc(self._pptx([paragraph(('Rev {{rev}}', False))]))
        other = self._doc(self._pptx([paragraph(('x', False))]), name='Other')
        payload = jwt_utils.decode_token(
            self.env, doc._filled_token(), config_utils.get_internal_jwt_secret(self.env),
        )
        self.assertEqual(payload['jacon_office_document'], doc.id)
        self.assertNotEqual(payload['jacon_office_document'], other.id)

    def test_a_file_without_placeholders_is_converted_as_it_is(self):
        doc = self._doc(self._pptx([paragraph(('nothing', False))]))
        body = self._convert(doc)
        self.assertIn('/onlyoffice/file/content/%s' % doc.attachment_id.id, body['url'])
        self.assertEqual(body['key'], 'pdfa-%s-%s' % (doc.attachment_id.id, doc.attachment_id.checksum))

    def test_a_document_that_cannot_be_changed_opens_as_a_view_of_the_filled_file(self):
        doc = self._doc(self._pptx([paragraph(('Rev {{rev}}', False))]))
        self.assertEqual(doc._editor_url(), '/onlyoffice/editor/%s' % doc.attachment_id.id)  # a Draft is edited
        self._release(doc)
        self.assertEqual(doc.with_user(self.manager)._editor_url(), '/jacon_office/document/%s/view' % doc.id)
        plain = self._doc(self._pptx([paragraph(('nothing', False))]), name='Plain')
        self._release(plain)
        self.assertEqual(
            plain.with_user(self.manager)._editor_url(), '/onlyoffice/editor/%s' % plain.attachment_id.id,
        )  # nothing to fill

    def test_two_requests_do_not_make_the_same_pdf_at_once(self):
        doc = self._doc(self._pptx([paragraph(('Rev {{rev}}', False))]))
        with patch.object(type(self.Document), '_take_conversion_lock', lambda rec: False),                 patch(DOCUMENT_MODULE + '.requests.post') as post:
            action = doc.action_view_pdf()
        self.assertEqual((action['tag'], action['params']['type']), ('display_notification', 'info'))
        post.assert_not_called()

    def test_a_file_is_scanned_once_per_request(self):
        doc = self._doc(self._pptx([paragraph(('Rev {{rev}}', False))]))
        with patch.object(office_placeholders, 'tokens_in', wraps=office_placeholders.tokens_in) as scan:
            for _i in range(4):
                doc._render_key()
                doc._placeholders_used()
        self.assertEqual(scan.call_count, 1)

    # -- templates -----------------------------------------------------

    def test_a_template_reports_its_placeholders(self):
        template = self.env['jacon.office.template'].create({
            'name': 'Deck', 'upload_filename': 'deck.pptx',
            'upload': __import__('base64').b64encode(self._pptx([paragraph(('{{rev}} {{rv}} {{partner.x}}', False))])),
        })
        report = template.placeholder_report
        self.assertIn('{{rev}}: OK', report)
        self.assertIn('{{rv}}: UNKNOWN', report)
        self.assertIn('{{partner.x}}: comes from the record', report)
        self.assertIn('{{released_by}}', str(template.placeholder_guide))  # the list of what can be used


@tagged('post_install', '-at_install', 'jacon_office')
class TestFilledRoutes(HttpCase):
    """The pages ONLYOFFICE and the users reach by HTTP.

    The server answers only for the databases its `dbfilter` shows (this project shows one): run these
    with `--db-filter=^<the test database>$`, otherwise they are skipped.
    """

    def setUp(self):
        super().setUp()
        pattern = config.get('dbfilter')
        if pattern and not re.match(pattern, self.env.cr.dbname):
            self.skipTest("The server's dbfilter does not show this database: HTTP requests would not reach it.")
        self.Document = self.env['jacon.office.document']
        self.env['ir.config_parameter'].set_param('onlyoffice_connector.internal_jwt_secret', 'internal-test-secret')
        self.partner = self.env['res.partner'].create({'name': 'Acme'})
        content = TestPlaceholders._pptx(self, [paragraph(('Rev {{rev}} {{state}}', False))])
        self.doc = self.Document.create({
            'name': 'Acme-Spec', 'kind': 'pptx', 'res_model': 'res.partner', 'res_id': self.partner.id,
            'file_content': content,
        })
        self.doc.state = 'released'
        user = self.env['res.users'].create({
            'name': 'Http Manager', 'login': 'http_manager', 'password': 'http_manager_pw',
            'group_ids': [(6, 0, [
                self.env.ref('base.group_user').id, self.env.ref('jacon_office.group_jacon_office_manager').id,
            ])],
        })
        self.authenticate('http_manager', 'http_manager_pw')

    def _text(self, content):
        return TestPlaceholders._paragraphs(self, content)

    def test_the_download_has_the_placeholders_filled(self):
        response = self.url_open('/jacon_office/document/%s/download' % self.doc.id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._text(response.content), ['Rev 1 Released'])

    def test_the_viewer_opens_the_filled_file_for_viewing_only(self):
        response = self.url_open('/jacon_office/document/%s/view' % self.doc.id)
        self.assertEqual(response.status_code, 200)
        self.assertIn('view-%s-' % self.doc.id, response.text)
        self.assertIn('/filled?oo_security_token=', response.text)
        self.assertNotIn('callbackUrl', response.text)
        self.assertIn('"mode": "view"', response.text)

    def test_the_filled_file_is_for_the_holder_of_its_token_only(self):
        url = '/jacon_office/document/%s/filled' % self.doc.id
        self.assertEqual(self.url_open(url).status_code, 404)
        self.assertEqual(self.url_open(url + '?oo_security_token=nonsense').status_code, 404)
        other = self.Document.create({
            'name': 'Other', 'kind': 'pptx', 'res_model': 'res.partner', 'res_id': self.partner.id,
        })
        self.assertEqual(self.url_open('%s?oo_security_token=%s' % (url, other._filled_token())).status_code, 404)
        response = self.url_open('%s?oo_security_token=%s' % (url, self.doc._filled_token()))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._text(response.content), ['Rev 1 Released'])
