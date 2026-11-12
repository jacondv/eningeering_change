import base64
import io
import zipfile
from unittest.mock import patch

from psycopg2 import IntegrityError

from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger


@tagged('post_install', '-at_install', 'jacon_office')
class TestOfficeDocument(TransactionCase):
    """The documents of a plain `res.partner`: the core addon knows no other record type."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Document = cls.env['jacon.office.document']
        cls.partner = cls.env['res.partner'].create({'name': 'Acme'})
        cls.other_partner = cls.env['res.partner'].create({'name': 'Other'})
        cls.user = cls.env['res.users'].create({
            'name': 'Office User', 'login': 'office_user',
            # Internal users may only read partners; the Contact Creation group lets them write too.
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id, cls.env.ref('base.group_partner_manager').id,
            ])],
        })

    def _doc(self, partner=None, **vals):
        values = {
            'name': 'Acme-Specification', 'kind': 'docx',
            'res_model': 'res.partner', 'res_id': (partner or self.partner).id,
        }
        values.update(vals)
        return self.Document.create(values)

    # -- the file -----------------------------------------------------

    def test_a_new_document_gets_a_blank_file_of_its_kind(self):
        for kind, folder in (('docx', 'word/'), ('xlsx', 'xl/'), ('pptx', 'ppt/')):
            doc = self._doc(name='Doc %s' % kind, kind=kind)
            attachment = doc.attachment_id
            self.assertEqual(attachment.name, 'Doc %s.%s' % (kind, kind))
            self.assertEqual((attachment.res_model, attachment.res_id), ('jacon.office.document', doc.id))
            with zipfile.ZipFile(io.BytesIO(attachment.raw)) as archive:
                self.assertTrue(any(n.startswith(folder) for n in archive.namelist()), kind)

    def test_an_uploaded_file_is_kept_as_it_is(self):
        blank = self.Document._blank_file('xlsx')
        doc = self._doc(kind='xlsx', file_content=blank)
        self.assertEqual(doc.attachment_id.raw, blank)

    def test_an_uploaded_file_must_be_of_the_kind_it_claims(self):
        with self.assertRaises(UserError):
            self._doc(kind='docx', file_content=b'not an office file')
        with self.assertRaises(UserError):
            self._doc(kind='docx', file_content=self.Document._blank_file('pptx'))

    def test_renaming_renames_the_file(self):
        doc = self._doc()
        doc.name = 'Renamed: spec/1'
        self.assertEqual(doc.attachment_id.name, 'Renamed- spec-1.docx')

    def test_the_type_and_the_record_cannot_change(self):
        doc = self._doc()
        with self.assertRaises(UserError):
            doc.kind = 'pptx'
        with self.assertRaises(UserError):
            doc.res_id = self.other_partner.id

    def test_deleting_a_document_deletes_its_file(self):
        doc = self._doc()
        attachment = doc.attachment_id
        doc.unlink()
        self.assertFalse(attachment.exists())

    # -- names --------------------------------------------------------

    @mute_logger('odoo.sql_db')
    def test_a_name_is_unique_per_record_whatever_its_case(self):
        self._doc()
        with self.assertRaises(IntegrityError), self.cr.savepoint():
            self._doc(name='acme-SPECIFICATION')
        self._doc(partner=self.other_partner)  # the same name on another record is fine

    def test_an_archived_document_frees_its_name(self):
        doc = self._doc()
        doc.active = False
        self.env.flush_all()
        self._doc()

    # -- access follows the record -----------------------------------

    def test_a_user_sees_the_documents_of_records_they_can_read(self):
        doc = self._doc()
        self.assertIn(doc, self.Document.with_user(self.user).search([]))
        self.assertEqual(doc.with_user(self.user).res_name, 'Acme')

    def _hide_acme_from_internal_users(self):
        self.env['ir.rule'].create({
            'name': 'Acme is secret',
            'model_id': self.env['ir.model']._get('res.partner').id,
            'domain_force': "[('name', '!=', 'Acme')]",
            'groups': [(4, self.env.ref('base.group_user').id)],
        })

    def test_a_user_cannot_see_the_documents_of_a_record_they_cannot_read(self):
        doc = self._doc()
        other = self._doc(partner=self.other_partner)
        self._hide_acme_from_internal_users()
        visible = self.Document.with_user(self.user).search([])
        self.assertNotIn(doc, visible)
        self.assertIn(other, visible)
        with self.assertRaises(AccessError):
            doc.with_user(self.user).read(['name'])
        # nor can they get at the file itself, e.g. through the editor
        with self.assertRaises(AccessError):
            doc.attachment_id.with_user(self.user).read(['raw'])

    def test_a_user_cannot_add_a_document_to_a_record_they_cannot_write(self):
        self._hide_acme_from_internal_users()
        with self.assertRaises(AccessError):
            self.Document.with_user(self.user).create({
                'name': 'Sneaky', 'kind': 'docx', 'res_model': 'res.partner', 'res_id': self.partner.id,
            })

    # -- locking ------------------------------------------------------

    def _lock(self, partner):
        """res.partner has no lock; give it one, as a model using the mixin would."""
        locked_ids = {partner.id}
        return patch.object(
            self.env.registry['res.partner'], '_office_is_locked',
            create=True, new=lambda rec: rec.id in locked_ids,
        )

    def test_a_locked_record_keeps_its_documents_readable_but_not_editable(self):
        doc = self._doc()
        user_doc = doc.with_user(self.user)
        with self._lock(self.partner):
            user_doc.read(['name'])
            user_doc.attachment_id.read(['raw'])
            with self.assertRaises(AccessError):
                user_doc.write({'description': 'edited'})
            with self.assertRaises(AccessError):
                user_doc.attachment_id.write({'raw': doc.attachment_id.raw})
            with self.assertRaises(UserError):
                self._doc(name='Another')
        user_doc.write({'description': 'edited'})  # unlocked again

    # -- the new document dialog -------------------------------------

    def _wizard(self, **vals):
        values = {'res_model': 'res.partner', 'res_id': self.partner.id}
        values.update(vals)
        return self.env['jacon.office.document.create.wizard'].create(values)

    def test_the_dialog_suggests_the_record_name_and_the_category(self):
        defaults = self.env['jacon.office.document.create.wizard'].with_context(
            default_res_model='res.partner', default_res_id=self.partner.id,
        ).default_get(['name', 'res_model', 'res_id'])
        self.assertEqual(defaults['name'], 'Acme-Specification')

    def test_the_dialog_keeps_a_name_the_user_typed(self):
        wizard = self._wizard(name='Acme-Specification', auto_name='Acme-Specification')
        wizard.category_id = self.env.ref('jacon_office.category_report')
        wizard._onchange_suggest_name()
        self.assertEqual(wizard.name, 'Acme-Report')
        wizard.name = 'My own title'
        wizard.category_id = self.env.ref('jacon_office.category_other')
        wizard._onchange_suggest_name()
        self.assertEqual(wizard.name, 'My own title')

    def test_the_dialog_creates_a_blank_or_an_uploaded_document(self):
        wizard = self._wizard(name='Blank one', kind='pptx')
        wizard.action_create()
        blank = self.Document.search([('name', '=', 'Blank one')])
        self.assertEqual(blank.kind, 'pptx')

        content = self.Document._blank_file('docx')
        wizard = self._wizard(
            name='Uploaded one', source='upload',
            upload=base64.b64encode(content), upload_filename='From my laptop.DOCX',
        )
        action = wizard.action_create_and_edit()
        uploaded = self.Document.search([('name', '=', 'Uploaded one')])
        self.assertEqual(uploaded.attachment_id.raw, content)
        self.assertEqual(action['tag'], 'jacon_office_open_editor')
        self.assertEqual(action['params']['url'], '/onlyoffice/editor/%s' % uploaded.attachment_id.id)

    def test_the_dialog_refuses_what_it_cannot_store(self):
        with self.assertRaises(UserError):
            self._wizard(name='x', source='upload').action_create()
        with self.assertRaises(UserError):
            self._wizard(
                name='x', source='upload', upload=base64.b64encode(b'x'), upload_filename='notes.txt',
            ).action_create()

    def test_open_goes_to_the_editor_and_download_to_the_file(self):
        doc = self._doc()
        self.assertEqual(doc.action_open_editor()['url'], '/onlyoffice/editor/%s' % doc.attachment_id.id)
        self.assertIn('/web/content/%s' % doc.attachment_id.id, doc.action_download()['url'])

    def test_the_document_leads_to_the_record_it_belongs_to(self):
        doc = self._doc()
        action = doc.action_open_record()
        self.assertEqual((action['res_model'], action['res_id']), ('res.partner', self.partner.id))
        self.partner.unlink()
        with self.assertRaises(UserError):
            doc.action_open_record()

    def test_the_link_to_the_record_follows_access_to_it(self):
        doc = self._doc()
        self._hide_acme_from_internal_users()
        with self.assertRaises(AccessError):
            doc.with_user(self.user).action_open_record()
