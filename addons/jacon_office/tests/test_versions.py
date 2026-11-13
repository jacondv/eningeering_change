import io
import json
import zipfile
from datetime import timedelta
from unittest.mock import MagicMock, patch

import requests

from odoo import fields
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
                cls.env.ref('jacon_office.group_jacon_office_editor').id,
            ])],
        })
        cls.manager = cls.env['res.users'].create({
            'name': 'Office Manager', 'login': 'rev_manager',
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id, cls.env.ref('base.group_partner_manager').id,
                cls.env.ref('jacon_office.group_jacon_office_manager').id,
            ])],
        })

    def _content(self, text):
        """A valid .docx whose content is `text`, so that two of them differ."""
        buffer = io.BytesIO(self.Document._blank_file('docx'))
        with zipfile.ZipFile(buffer, 'a') as archive:
            # a fixed time stamp: the same text must give the very same bytes
            archive.writestr(zipfile.ZipInfo('word/note.txt', (2026, 1, 1, 0, 0, 0)), text)
        return buffer.getvalue()

    def _doc(self, **vals):
        values = {'name': 'Acme-Specification', 'kind': 'docx', 'res_model': 'res.partner', 'res_id': self.partner.id}
        values.update(vals)
        return self.Document.create(values)

    def _save(self, doc, text, user=None):
        """What ONLYOFFICE does when an edit is saved: the file's content is written."""
        attachment = doc.attachment_id.with_user(user) if user else doc.attachment_id
        attachment.write({'raw': self._content(text)})

    def _release(self, doc, user=None, reason=None):
        """Submit the document and have a Manager release it (the editor is never really open here)."""
        with patch.object(type(self.Document), '_editor_is_open', lambda rec: False):
            doc.with_user(user or self.user).action_submit()
        doc.with_user(self.manager).action_approve()
        return doc

    # -- the workflow --------------------------------------------------

    def test_editing_a_draft_saves_in_place_without_any_rev(self):
        doc = self._doc()
        self.assertEqual((doc.state, doc.revision, doc.version_count), ('draft', 1, 0))
        self._save(doc, 'second', user=self.user)
        self._save(doc, 'third', user=self.user)
        self.assertEqual((doc.revision, doc.version_count), (1, 0))
        self.assertEqual(doc.attachment_id.raw, self._content('third'))
        self.assertEqual(doc.last_edit_user_id, self.user)
        self.assertEqual(doc.pdf_state, 'pending')

    def test_saving_the_same_content_changes_nothing(self):
        doc = self._doc()
        before = doc.last_edit_date
        doc.attachment_id.write({'raw': doc.attachment_id.raw})
        self.assertEqual(doc.last_edit_date, before)

    def test_submitting_locks_the_document_and_asks_the_managers(self):
        doc = self._doc()
        self._save(doc, 'content')
        with patch.object(type(self.Document), '_editor_is_open', lambda rec: False):
            doc.with_user(self.user).action_submit()
        self.assertEqual(doc.state, 'review')
        self.assertEqual(doc.submitted_by_id, self.user)
        self.assertIn(self.manager, doc.activity_ids.user_id)
        self.assertFalse(doc.with_user(self.user).can_edit)
        self.assertTrue(doc.with_user(self.user).can_work)
        self.assertTrue(doc.with_user(self.manager).can_approve)
        self.assertFalse(doc.with_user(self.user).can_approve)
        with self.assertRaises(AccessError):
            doc.with_user(self.user).write({'name': 'Changed'})
        with self.assertRaises(AccessError):  # ONLYOFFICE saving: the file is locked too
            doc.attachment_id.with_user(self.user).write({'raw': self._content('late')})
        # taking it back unlocks it
        doc.with_user(self.user).action_recall()
        self.assertEqual(doc.state, 'draft')
        self.assertFalse(doc.activity_ids)
        doc.with_user(self.user).write({'name': 'Changed'})

    def test_a_document_still_open_in_the_editor_cannot_be_submitted(self):
        doc = self._doc()
        with patch.object(type(self.Document), '_editor_is_open', lambda rec: True):
            with self.assertRaises(UserError):
                doc.with_user(self.user).action_submit()
        self.assertEqual(doc.state, 'draft')

    def test_approving_releases_the_document_and_keeps_its_file_as_a_rev(self):
        doc = self._doc()
        self._save(doc, 'content')
        self._release(doc)
        self.assertEqual((doc.state, doc.revision, doc.version_count), ('released', 1, 1))
        self.assertEqual(doc.approved_by_id, self.manager)
        rev = doc.version_ids
        self.assertEqual((rev.number, rev.user_id, rev.note), (1, self.manager, 'First release'))
        self.assertEqual(rev.attachment_id.raw, self._content('content'))
        self.assertFalse(doc.activity_ids)
        # locked for everybody but still readable and downloadable
        self.assertFalse(doc.with_user(self.manager).can_edit)
        with self.assertRaises(AccessError):
            doc.with_user(self.manager).write({'name': 'Changed'})
        with self.assertRaises(AccessError):
            doc.attachment_id.with_user(self.manager).write({'raw': self._content('late')})
        doc.with_user(self.user).action_download()
        doc.with_user(self.user).message_post(body='A comment')  # commenting stays possible

    def test_only_a_manager_approves_or_rejects(self):
        doc = self._doc()
        with patch.object(type(self.Document), '_editor_is_open', lambda rec: False):
            doc.with_user(self.user).action_submit()
        with self.assertRaises(AccessError):
            doc.with_user(self.user).action_approve()
        with self.assertRaises(AccessError):
            doc.with_user(self.user).action_reject('no')
        self.assertEqual(doc.state, 'review')

    def test_rejecting_needs_a_reason_and_sends_it_back_to_draft(self):
        doc = self._doc()
        with patch.object(type(self.Document), '_editor_is_open', lambda rec: False):
            doc.with_user(self.user).action_submit()
        with self.assertRaises(UserError):
            doc.with_user(self.manager).action_reject('  ')
        doc.with_user(self.manager).action_reject('Wrong logo')
        self.assertEqual((doc.state, doc.reject_reason), ('draft', 'Wrong logo'))
        self.assertTrue(doc.with_user(self.user).can_edit)
        # the next submission starts clean
        with patch.object(type(self.Document), '_editor_is_open', lambda rec: False):
            doc.with_user(self.user).action_submit()
        self.assertFalse(doc.reject_reason)

    def test_steps_only_work_from_the_right_state(self):
        doc = self._doc()
        with self.assertRaises(UserError):
            doc.with_user(self.manager).action_approve()  # not submitted
        with self.assertRaises(UserError):
            doc.with_user(self.user).action_recall()
        with self.assertRaises(UserError):
            doc.with_user(self.user).action_new_revision('why')  # not released
        self._release(doc)
        with self.assertRaises(UserError):
            doc.with_user(self.user).action_submit()  # already released

    def test_a_new_rev_is_a_draft_that_starts_from_the_released_file(self):
        doc = self._doc()
        self._save(doc, 'one')
        self._release(doc)
        with self.assertRaises(UserError):
            doc.with_user(self.user).action_new_revision(' ')
        doc.with_user(self.user).action_new_revision('Customer asked for a change')
        self.assertEqual((doc.state, doc.revision, doc.revision_reason), ('draft', 2, 'Customer asked for a change'))
        self.assertEqual(doc.attachment_id.raw, self._content('one'))
        self._save(doc, 'two', user=self.user)
        self.assertEqual(doc.version_ids.attachment_id.raw, self._content('one'))  # Rev 1 untouched
        self._release(doc)
        self.assertEqual(doc.version_ids.sorted('number').mapped('number'), [1, 2])
        self.assertEqual(doc.version_ids.filtered(lambda v: v.number == 2).note, 'Customer asked for a change')

    def test_a_new_rev_can_start_from_an_older_released_rev(self):
        doc = self._doc()
        self._save(doc, 'one')
        self._release(doc)
        doc.with_user(self.user).action_new_revision('change')
        self._save(doc, 'two')
        self._release(doc)
        rev1 = doc.version_ids.filtered(lambda v: v.number == 1)
        action = rev1.with_user(self.user).action_new_revision()
        self.assertEqual(action['context']['default_version_id'], rev1.id)
        wizard = self.env['jacon.office.document.reason.wizard'].with_user(self.user).create({
            'document_id': doc.id, 'version_id': rev1.id, 'mode': 'new_rev', 'reason': 'Back to the first',
        })
        wizard.action_confirm()
        self.assertEqual((doc.state, doc.revision), ('draft', 3))
        self.assertEqual(doc.attachment_id.raw, self._content('one'))

    def test_the_reason_dialog_rejects_or_opens_a_rev(self):
        doc = self._doc()
        with patch.object(type(self.Document), '_editor_is_open', lambda rec: False):
            doc.with_user(self.user).action_submit()
        self.assertEqual(doc.with_user(self.manager).action_ask_reject()['context']['default_mode'], 'reject')
        wizard = self.env['jacon.office.document.reason.wizard'].with_user(self.manager).create({
            'document_id': doc.id, 'mode': 'reject', 'reason': 'Not ready',
        })
        wizard.action_confirm()
        self.assertEqual((doc.state, doc.reject_reason), ('draft', 'Not ready'))

    def test_the_managers_are_told_and_the_record_logs_what_happens(self):
        doc = self._doc()
        with patch.object(type(self.Document), '_editor_is_open', lambda rec: False):
            doc.with_user(self.user).action_submit()
        submitted = doc.message_ids[0]
        self.assertIn('submitted Rev 1 for review', submitted.body)
        self.assertIn(self.manager, doc.activity_ids.user_id)  # the Managers are told by their activity: no second notice
        self.assertFalse(submitted.partner_ids)
        self.assertIn('Document Acme-Specification', self.partner.message_ids[0].body)  # also on the record's chatter
        doc.with_user(self.manager).action_approve()
        self.assertIn(self.user.partner_id, doc.message_ids[0].partner_ids)  # the submitter hears of the release
        doc.with_user(self.user).action_new_revision('Customer change')
        opened = doc.message_ids[0]
        self.assertIn('opened Rev 2', opened.body)
        self.assertIn('Customer change', opened.body)
        self.assertIn(self.manager.partner_id, opened.partner_ids)  # a released document is being changed
        self.assertIn('opened Rev 2', self.partner.message_ids[0].body)

    def test_the_details_and_history_open_the_documents_form(self):
        doc = self._doc()
        action = doc.with_user(self.user).action_open_form()
        self.assertEqual((action['res_model'], action['res_id']), ('jacon.office.document', doc.id))

    def test_the_workflow_fields_cannot_be_written_or_set_by_users(self):
        doc = self._doc()
        with self.assertRaises(UserError):
            doc.with_user(self.user).write({'state': 'released'})
        with self.assertRaises(UserError):
            doc.with_user(self.user).write({'revision': 9})
        sneaky = self.Document.with_user(self.user).create({
            'name': 'Sneaky', 'kind': 'docx', 'res_model': 'res.partner', 'res_id': self.partner.id,
            'state': 'released', 'revision': 5,
        })
        self.assertEqual((sneaky.state, sneaky.revision), ('draft', 1))

    def test_archiving_works_in_any_state_but_nothing_else_does(self):
        doc = self._doc()
        self._release(doc)
        as_user = doc.with_user(self.user)
        as_user.action_archive()
        self.assertFalse(doc.active)
        as_user.action_unarchive()
        self.assertTrue(doc.active)
        # a forged context does not open the lock
        with self.assertRaises(AccessError):
            as_user.with_context(jacon_office_skip_state_lock=True).write({'name': 'Sneaky'})

    def test_delete_old_revs_keeps_the_latest_one(self):
        doc = self._doc()
        self._save(doc, 'one')
        self._release(doc)
        doc.with_user(self.user).action_new_revision('change')
        self._save(doc, 'two')
        self._release(doc)
        old = doc.version_ids.filtered(lambda v: v.number == 1).attachment_id
        action = doc.action_delete_old_versions()
        self.assertEqual(action['tag'], 'display_notification')
        self.assertEqual(doc.version_ids.mapped('number'), [2])
        self.assertFalse(old.exists())
        self.assertEqual(doc.version_ids.attachment_id.raw, self._content('two'))
        self.assertIn('deleted 1 older Revs', doc.message_ids[0].body)
        # nothing left to delete is not an error
        self.assertEqual(doc.action_delete_old_versions()['params']['type'], 'info')

    def test_documents_from_before_the_workflow_are_drafts_with_their_old_revs(self):
        doc = self._doc()
        doc.state = 'draft'
        self.env['jacon.office.document.version'].create({
            'document_id': doc.id, 'number': 1, 'file_content': self._content('old'),
        })
        doc.revision = 2
        self._release(doc)  # released as Rev 2, next to the old Rev 1
        self.assertEqual(doc.version_ids.sorted('number').mapped('number'), [1, 2])

    def test_deleting_a_document_deletes_its_revs_and_their_files(self):
        doc = self._doc()
        self._release(doc)
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
        self._release(doc)
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

    def test_revs_of_a_locked_record_cannot_be_deleted_or_built_on(self):
        doc = self._doc()
        self._release(doc)
        rev = doc.version_ids.with_user(self.user)
        with patch.object(
            self.env.registry['res.partner'], '_office_is_locked', create=True, new=lambda rec: True,
        ):
            with self.assertRaises(AccessError):
                rev.action_delete()
            with self.assertRaises(AccessError):
                doc.with_user(self.user).action_new_revision('change')
            rev.action_download()  # still readable
        rev.with_user(self.manager).action_delete()

    # -- bulk -----------------------------------------------------------

    def test_documents_can_be_archived_and_changed_in_bulk(self):
        docs = self._doc(name='One') | self._doc(name='Two')
        category = self.env.ref('jacon_office.category_report')
        docs.with_user(self.user).write({'category_id': category.id, 'author': 'Someone Outside'})
        self.assertEqual(docs.category_id, category)
        self.assertEqual(docs.mapped('author'), ['Someone Outside'] * 2)
        docs.with_user(self.user).action_archive()
        self.assertFalse(docs.filtered('active'))
        docs.with_user(self.user).action_unarchive()
        self.assertEqual(len(docs.filtered('active')), 2)
        with self.assertRaises(AccessError):
            docs.with_user(self.user).unlink()  # deleting is for Managers
        docs.with_user(self.manager).unlink()
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
                doc.with_user(self.manager).unlink()  # not even a Manager, while the record is locked
        self.assertFalse(doc.is_locked)

    # -- PDF ------------------------------------------------------------

    def _conversions(self, post_mock):
        """How many times ONLYOFFICE was asked to convert (not to say whether a document is open)."""
        return len([call for call in post_mock.call_args_list if 'converter' in call.args[0]])

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
            self.assertEqual(self._conversions(post_mock), 1)

            # a new content makes the PDF stale; viewing it makes it again
            self._save(doc, 'two')
            self.assertFalse(doc._pdf_is_current())
            doc.action_view_pdf()
            self.assertTrue(doc._pdf_is_current())
            self.assertEqual(self._conversions(post_mock), 2)

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
        self.assertEqual((body['filetype'], body['outputtype'], body['async']), ('docx', 'pdfa', False))
        self.assertTrue(body['key'].startswith('pdfa-%s-' % doc.attachment_id.id))
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

    def test_a_pdf_that_failed_is_not_tried_again_at_every_click(self):
        doc = self._doc()
        with patch(DOCUMENT_MODULE + '.requests.post', side_effect=requests.ConnectionError('refused')) as post:
            doc.action_view_pdf()
            self.assertEqual(post.call_count, 1)
            action = doc.action_view_pdf()  # a moment later
            self.assertEqual(post.call_count, 1)
            self.assertEqual(action['params']['type'], 'danger')
            doc.pdf_failed_date = fields.Datetime.now() - timedelta(minutes=6)
            doc.action_view_pdf()
            self.assertEqual(post.call_count, 2)  # a while later: tried again

    def test_a_document_with_the_older_revs_of_before_the_workflow_can_be_released(self):
        doc = self._doc()
        for number in (1, 2, 3):
            self.env['jacon.office.document.version'].sudo().create({
                'document_id': doc.id, 'number': number, 'file_content': self._content('old %s' % number),
            })
        self.assertEqual(doc.revision, 1)  # the Revs of its saves are already numbered 1..3
        self._release(doc)
        self.assertEqual((doc.revision, max(doc.version_ids.mapped('number'))), (4, 4))
        doc.action_new_revision('Change')
        self.assertEqual(doc.revision, 5)

    def test_the_models_that_own_documents_follow_the_documents(self):
        self._doc()
        self.env.cr.cache.pop('jacon_office_owner_models', None)
        self.assertEqual(self.env['jacon.office.document']._owner_models().count('res.partner'), 1)
        other = self.env['jacon.office.document'].create({
            'name': 'On a user', 'kind': 'docx', 'res_model': 'res.users', 'res_id': self.env.user.id,
        })
        self.assertIn('res.users', self.env['jacon.office.document']._owner_models())  # forgotten on create
        other.unlink()
        self.assertNotIn('res.users', self.env['jacon.office.document']._owner_models())

    def test_an_unexpected_converter_error_is_a_failed_pdf_not_a_crash(self):
        doc = self._doc()

        def convert(doc, attachment, output_type):
            raise KeyError('endConvert')

        with patch.object(self.env.registry['jacon.office.document'], '_onlyoffice_convert', convert):
            self.assertFalse(doc._convert_to_pdf())
        self.assertEqual(doc.pdf_state, 'failed')
        self.assertIn('endConvert', doc.pdf_error)

    def test_a_reply_that_is_not_a_pdf_is_a_failure(self):
        doc = self._doc()
        post, get = self._convert_ok(pdf=b'<html>login</html>')
        with post, get:
            self.assertFalse(doc._convert_to_pdf())
        self.assertEqual(doc.pdf_state, 'failed')

    def test_no_pdf_is_made_until_someone_asks_for_it(self):
        doc = self._doc()
        post, get = self._convert_ok()
        with post as post_mock, get:
            self._save(doc, 'two')
            self.assertEqual(self._conversions(post_mock), 0)
            self.assertEqual(doc.pdf_state, 'pending')
            self.assertFalse(doc.pdf_attachment_id)
            doc.action_view_pdf()
            self.assertEqual(self._conversions(post_mock), 1)

    def test_renaming_renames_the_pdf(self):
        doc = self._doc()
        post, get = self._convert_ok()
        with post, get:
            doc._convert_to_pdf()
        doc.name = 'Renamed'
        self.assertEqual(doc.pdf_attachment_id.name, 'Renamed.pdf')

    # -- an editor still open ------------------------------------------

    def _command_reply(self, **reply):
        response = MagicMock(status_code=200)
        response.json.return_value = reply
        return patch(DOCUMENT_MODULE + '.requests.post', return_value=response)

    def test_a_document_open_in_the_editor_is_noticed(self):
        doc = self._doc()
        with self._command_reply(error=0, users=['2']):
            self.assertTrue(doc._editor_is_open())
        with self._command_reply(error=0, users=[]):
            self.assertFalse(doc._editor_is_open())  # closed (its file may still be on its way)
        with self._command_reply(error=1):
            self.assertFalse(doc._editor_is_open())  # ONLYOFFICE does not know this content
        with patch(DOCUMENT_MODULE + '.requests.post', side_effect=requests.ConnectionError('down')):
            self.assertFalse(doc._editor_is_open())  # unknown: no false alarm

    def test_viewing_the_pdf_of_a_document_open_in_the_editor_warns(self):
        doc = self._doc()
        post, get = self._convert_ok()
        with post, get:
            doc._convert_to_pdf()
        with patch.object(type(self.env['jacon.office.document']), '_editor_is_open', lambda rec: True), \
                patch.object(self.env.registry['bus.bus'], '_sendone') as sendone:
            action = doc.action_view_pdf()
        self.assertEqual(action['type'], 'ir.actions.act_url')  # the PDF still opens
        args = sendone.call_args.args
        self.assertEqual(args[1], 'simple_notification')
        self.assertEqual(args[2]['type'], 'warning')
