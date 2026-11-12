import io
import json
import zipfile
from unittest.mock import MagicMock, patch

import requests

from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged

DOCUMENT_MODULE = 'odoo.addons.jacon_office.models.jacon_office_document'


@tagged('post_install', '-at_install', 'jacon_office')
class TestRevs(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Document = cls.env['jacon.office.document']
        # The connector makes this secret the first time it needs it, which commits: not in a test.
        cls.env['ir.config_parameter'].set_param('onlyoffice_connector.internal_jwt_secret', 'internal-test-secret')
        cls.partner = cls.env['res.partner'].create({'name': 'Acme'})
        cls.user = cls.env['res.users'].create({
            'name': 'Office User', 'login': 'rev_user',
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id, cls.env.ref('base.group_partner_manager').id,
            ])],
        })

    def _content(self, text):
        """A valid .docx whose content is `text`, so that two of them differ."""
        buffer = io.BytesIO(self.Document._blank_file('docx'))
        with zipfile.ZipFile(buffer, 'a') as archive:
            archive.writestr('word/note.txt', text)
        return buffer.getvalue()

    def _doc(self, **vals):
        values = {'name': 'Acme-Specification', 'kind': 'docx', 'res_model': 'res.partner', 'res_id': self.partner.id}
        values.update(vals)
        return self.Document.create(values)

    def _save(self, doc, text, user=None):
        """What ONLYOFFICE does when an edit is saved: the file's content is written."""
        attachment = doc.attachment_id.with_user(user) if user else doc.attachment_id
        attachment.write({'raw': self._content(text)})

    def _set_keep(self, value):
        self.env['ir.config_parameter'].set_param('jacon_office.versions_to_keep', value)

    # -- Revs ---------------------------------------------------------

    def test_saving_new_content_keeps_the_old_content_as_a_rev(self):
        doc = self._doc()
        first = doc.attachment_id.raw
        self.assertEqual((doc.revision, doc.version_count), (1, 0))
        self.assertEqual(doc.last_edit_user_id, self.env.user)

        self._save(doc, 'second', user=self.user)
        self.assertEqual((doc.revision, doc.version_count), (2, 1))
        rev = doc.version_ids
        self.assertEqual(rev.number, 1)
        self.assertEqual(rev.attachment_id.raw, first)
        self.assertEqual(rev.user_id, self.env.user)  # who saved the content that was replaced
        self.assertEqual(doc.last_edit_user_id, self.user)
        self.assertEqual(doc.pdf_state, 'pending')

    def test_saving_the_same_content_makes_no_rev(self):
        doc = self._doc()
        doc.attachment_id.write({'raw': doc.attachment_id.raw})
        self.assertEqual((doc.revision, doc.version_count), (1, 0))

    def test_only_the_newest_revs_are_kept(self):
        doc = self._doc()
        for text in ('two', 'three', 'four', 'five', 'six'):
            self._save(doc, text)
        self.assertEqual(doc.revision, 6)
        self.assertEqual(doc.version_ids.mapped('number'), [5, 4, 3])  # the default is 3
        self._set_keep(1)
        self._save(doc, 'seven')
        self.assertEqual(doc.version_ids.mapped('number'), [6])

    def test_zero_keeps_no_rev_at_all(self):
        self._set_keep(0)
        doc = self._doc()
        self._save(doc, 'two')
        self.assertEqual((doc.revision, doc.version_count), (2, 0))
        self.assertEqual(doc.attachment_id.raw, self._content('two'))

    def test_a_setting_that_is_not_a_number_means_the_default(self):
        self._set_keep('lots')
        self.assertEqual(self.Document._versions_to_keep(), 3)

    def test_delete_old_revs_keeps_the_current_content(self):
        doc = self._doc()
        self._save(doc, 'two')
        self._save(doc, 'three')
        attachments = doc.version_ids.attachment_id
        action = doc.action_delete_old_versions()
        self.assertEqual(action['tag'], 'display_notification')
        self.assertFalse(doc.version_ids)
        self.assertFalse(attachments.exists())
        self.assertEqual(doc.attachment_id.raw, self._content('three'))
        self.assertIn('deleted 2 previous Revs', doc.message_ids[0].body)
        # nothing left to delete is not an error
        self.assertEqual(doc.action_delete_old_versions()['params']['type'], 'info')

    def test_restoring_a_rev_makes_it_current_and_keeps_what_was_current(self):
        doc = self._doc()
        first = doc.attachment_id.raw
        self._save(doc, 'two')
        rev1 = doc.version_ids
        rev1.action_restore()
        self.assertEqual(doc.attachment_id.raw, first)
        self.assertEqual(doc.revision, 3)
        self.assertEqual(doc.version_ids.sorted('number').mapped('number'), [1, 2])
        self.assertEqual(doc.version_ids.filtered(lambda v: v.number == 2).attachment_id.raw, self._content('two'))

    def test_deleting_a_document_deletes_its_revs_and_their_files(self):
        doc = self._doc()
        self._save(doc, 'two')
        attachments = doc.version_ids.attachment_id | doc.attachment_id
        doc.unlink()
        self.assertFalse(attachments.exists())

    def test_the_rev_list_opens_for_the_document(self):
        doc = self._doc()
        action = doc.action_view_versions()
        self.assertEqual(action['res_model'], 'jacon.office.document.version')
        self.assertEqual(action['domain'], [('document_id', '=', doc.id)])

    # -- Revs follow the document's access ---------------------------

    def test_revs_are_only_for_those_who_can_see_the_document(self):
        doc = self._doc()
        self._save(doc, 'two')
        rev = doc.version_ids
        Version = self.env['jacon.office.document.version'].with_user(self.user)
        self.assertEqual(Version.search([]), rev)
        rev.with_user(self.user).attachment_id.read(['raw'])

        self.env['ir.rule'].create({
            'name': 'Acme is secret',
            'model_id': self.env['ir.model']._get('res.partner').id,
            'domain_force': "[('name', '!=', 'Acme')]",
            'groups': [(4, self.env.ref('base.group_user').id)],
        })
        self.assertFalse(Version.search([]))
        with self.assertRaises(AccessError):
            rev.with_user(self.user).read(['number'])
        with self.assertRaises(AccessError):
            rev.attachment_id.with_user(self.user).read(['raw'])

    def test_revs_of_a_locked_record_cannot_be_deleted_or_restored(self):
        doc = self._doc()
        self._save(doc, 'two')
        rev = doc.version_ids.with_user(self.user)
        with patch.object(
            self.env.registry['res.partner'], '_office_is_locked', create=True, new=lambda rec: True,
        ):
            with self.assertRaises(AccessError):
                rev.action_delete()
            with self.assertRaises(AccessError):
                rev.action_restore()
            rev.action_download()  # still readable
        rev.action_delete()

    # -- bulk -----------------------------------------------------------

    def test_documents_can_be_archived_and_changed_in_bulk(self):
        docs = self._doc(name='One') | self._doc(name='Two')
        category = self.env.ref('jacon_office.category_report')
        docs.with_user(self.user).write({'category_id': category.id, 'author_id': self.user.id})
        self.assertEqual(docs.category_id, category)
        self.assertEqual(docs.author_id, self.user)
        docs.with_user(self.user).action_archive()
        self.assertFalse(docs.filtered('active'))
        docs.with_user(self.user).action_unarchive()
        self.assertEqual(len(docs.filtered('active')), 2)
        docs.with_user(self.user).unlink()
        self.assertFalse(docs.exists())

    def test_a_locked_record_refuses_bulk_changes(self):
        doc = self._doc()
        with patch.object(
            self.env.registry['res.partner'], '_office_is_locked', create=True, new=lambda rec: True,
        ):
            self.assertTrue(doc.is_locked)
            with self.assertRaises(AccessError):
                doc.with_user(self.user).action_archive()
            with self.assertRaises(AccessError):
                doc.with_user(self.user).unlink()
        self.assertFalse(doc.is_locked)

    # -- PDF ------------------------------------------------------------

    def _convert_ok(self, pdf=b'%PDF-1.7 fake'):
        converter = MagicMock(status_code=200)
        converter.json.return_value = {'endConvert': True, 'fileUrl': 'http://onlyoffice/cache/files/output.pdf'}
        download = MagicMock(status_code=200, content=pdf)
        return (
            patch(DOCUMENT_MODULE + '.requests.post', return_value=converter),
            patch(DOCUMENT_MODULE + '.requests.get', return_value=download),
        )

    def test_the_pdf_is_made_from_the_current_file_and_reused(self):
        doc = self._doc()
        self.assertEqual(doc.pdf_state, 'pending')
        self.assertFalse(doc._pdf_is_current())
        post, get = self._convert_ok()
        with post as post_mock, get:
            self.assertTrue(doc._convert_to_pdf())
            self.assertEqual(doc.pdf_state, 'ready')
            self.assertTrue(doc._pdf_is_current())
            self.assertEqual(doc.pdf_attachment_id.mimetype, 'application/pdf')
            self.assertEqual(doc.pdf_attachment_id.name, 'Acme-Specification.pdf')
            self.assertEqual(doc.pdf_attachment_id.raw, b'%PDF-1.7 fake')
            # viewing it again does not convert again
            self.assertIn('/web/content/%s/' % doc.pdf_attachment_id.id, doc.action_view_pdf()['url'])
            self.assertEqual(post_mock.call_count, 1)

            # a new content makes the PDF stale; viewing it makes it again
            self._save(doc, 'two')
            self.assertFalse(doc._pdf_is_current())
            doc.action_view_pdf()
            self.assertTrue(doc._pdf_is_current())
            self.assertEqual(post_mock.call_count, 2)

    def test_the_conversion_asks_onlyoffice_with_a_signed_request(self):
        self.env['ir.config_parameter'].set_param('onlyoffice_connector.doc_server_jwt_secret', 'a-test-secret-long-enough-for-hs256')
        self.env['ir.config_parameter'].set_param('onlyoffice_connector.doc_server_inner_url', 'http://onlyoffice/')
        self.env['ir.config_parameter'].set_param('onlyoffice_connector.doc_server_odoo_url', 'http://odoo:8069/')
        doc = self._doc()
        post, get = self._convert_ok()
        with post as post_mock, get:
            doc._convert_to_pdf()
        args, kwargs = post_mock.call_args
        self.assertTrue(args[0].startswith('http://onlyoffice/converter'))
        body = json.loads(kwargs['data'])
        self.assertEqual((body['filetype'], body['outputtype'], body['async']), ('docx', 'pdf', False))
        self.assertTrue(body['key'].startswith('pdf-%s-' % doc.attachment_id.id))
        self.assertIn('http://odoo:8069/onlyoffice/file/content/%s?oo_security_token=' % doc.attachment_id.id, body['url'])
        self.assertTrue(body['token'])
        self.assertTrue(kwargs['headers']['Authorization'].startswith('Bearer '))

    def test_a_failed_conversion_is_reported_and_keeps_the_old_pdf(self):
        doc = self._doc()
        post, get = self._convert_ok()
        with post, get:
            doc._convert_to_pdf()
        self._save(doc, 'two')
        old_pdf = doc.pdf_attachment_id.raw
        with patch(DOCUMENT_MODULE + '.requests.post', side_effect=requests.ConnectionError('refused')):
            self.assertFalse(doc._convert_to_pdf())
            self.assertEqual(doc.pdf_state, 'failed')
            self.assertIn('refused', doc.pdf_error)
            # reported, not raised: an exception would roll the recorded failure back
            action = doc.action_view_pdf()
            self.assertEqual((action['tag'], action['params']['type']), ('display_notification', 'danger'))
            self.assertIn('refused', action['params']['message'])
            self.assertEqual(doc.pdf_state, 'failed')
        self.assertEqual(doc.pdf_attachment_id.raw, old_pdf)

    def test_a_document_the_converter_chokes_on_does_not_stop_the_others(self):
        broken = self._doc(name='Broken')
        fine = self._doc(name='Fine')

        def convert(doc, attachment, output_type):
            if doc.name == 'Broken':
                raise KeyError('endConvert')
            return b'%PDF-1.7 fine'

        with patch.object(self.env.registry['jacon.office.document'], '_onlyoffice_convert', convert), \
                patch.object(self.env.registry['ir.cron'], '_commit_progress', return_value=float('inf')):
            self.Document._cron_convert_pending_pdfs()
        self.assertEqual((broken.pdf_state, fine.pdf_state), ('failed', 'ready'))

    def test_a_rev_cannot_be_restored_when_none_is_kept(self):
        doc = self._doc()
        self._save(doc, 'two')
        rev = doc.version_ids
        self._set_keep(0)
        with self.assertRaises(UserError):
            rev.action_restore()
        self.assertEqual(doc.attachment_id.raw, self._content('two'))

    def test_a_reply_that_is_not_a_pdf_is_a_failure(self):
        doc = self._doc()
        post, get = self._convert_ok(pdf=b'<html>login</html>')
        with post, get:
            self.assertFalse(doc._convert_to_pdf())
        self.assertEqual(doc.pdf_state, 'failed')

    def test_the_cron_makes_the_pending_pdfs(self):
        doc = self._doc()
        other = self._doc(name='Other')
        post, get = self._convert_ok()
        # Between documents the cron commits its progress, which a test must not do.
        with post, get, patch.object(self.env.registry['ir.cron'], '_commit_progress', return_value=float('inf')):
            self.Document._cron_convert_pending_pdfs()
        self.assertEqual((doc | other).mapped('pdf_state'), ['ready', 'ready'])

    def test_renaming_renames_the_pdf(self):
        doc = self._doc()
        post, get = self._convert_ok()
        with post, get:
            doc._convert_to_pdf()
        doc.name = 'Renamed'
        self.assertEqual(doc.pdf_attachment_id.name, 'Renamed.pdf')
