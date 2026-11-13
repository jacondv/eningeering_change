import base64
from unittest.mock import patch

from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'jacon_office')
class TestRolesAndTemplates(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Document = cls.env['jacon.office.document']
        cls.Template = cls.env['jacon.office.template']
        cls.partner = cls.env['res.partner'].create({'name': 'Acme'})
        cls.viewer = cls._user('viewer')
        cls.editor = cls._user('editor', 'jacon_office.group_jacon_office_editor')
        cls.manager = cls._user('manager', 'jacon_office.group_jacon_office_manager')

    @classmethod
    def _user(cls, login, *groups):
        group_ids = [cls.env.ref(name).id for name in ('base.group_user', 'base.group_partner_manager', *groups)]
        return cls.env['res.users'].create({'name': login.title(), 'login': 'role_' + login, 'group_ids': [(6, 0, group_ids)]})

    def _doc(self, **vals):
        values = {'name': 'Acme-Specification', 'kind': 'docx', 'res_model': 'res.partner', 'res_id': self.partner.id}
        values.update(vals)
        return self.Document.create(values)

    def _template(self, name='Company deck', kind='pptx', filename=None, **vals):
        values = {
            'name': name, 'upload_filename': filename or 'company.%s' % kind,
            'upload': base64.b64encode(self.Document._blank_file(kind)),
        }
        values.update(vals)
        return self.Template.create(values)

    # -- levels --------------------------------------------------------

    def test_an_internal_user_is_a_viewer_and_nothing_more_by_default(self):
        fresh = self._user('fresh')
        self.assertTrue(fresh.has_group('jacon_office.group_jacon_office_viewer'))
        self.assertFalse(fresh.has_group('jacon_office.group_jacon_office_editor'))
        self.assertTrue(self.editor.has_group('jacon_office.group_jacon_office_viewer'))  # each level includes the one before
        self.assertTrue(self.manager.has_group('jacon_office.group_jacon_office_editor'))

    def test_settings_administrators_are_managers(self):
        self.assertTrue(self.env.ref('base.user_admin').has_group('jacon_office.group_jacon_office_manager'))

    def test_a_viewer_only_looks(self):
        doc = self._doc()
        as_viewer = doc.with_user(self.viewer)
        self.assertEqual(as_viewer.name, 'Acme-Specification')
        self.assertFalse(as_viewer.can_edit)
        self.assertEqual(as_viewer.action_download()['type'], 'ir.actions.act_url')
        self.assertEqual(self.env['jacon.office.document.version'].with_user(self.viewer).search([]), self.env['jacon.office.document.version'])
        with self.assertRaises(AccessError):
            as_viewer.write({'name': 'Renamed'})
        with self.assertRaises(AccessError):
            self.Document.with_user(self.viewer).create({
                'name': 'Mine', 'kind': 'docx', 'res_model': 'res.partner', 'res_id': self.partner.id,
            })
        with self.assertRaises(AccessError):
            as_viewer.unlink()
        # the file is read-only for them too, so the editor opens it for viewing only
        with self.assertRaises(AccessError):
            doc.attachment_id.with_user(self.viewer).write({'raw': self.Document._blank_file('docx') + b'x'})
        with self.assertRaises(AccessError):
            self.env['jacon.office.document.create.wizard'].with_user(self.viewer).create({
                'res_model': 'res.partner', 'res_id': self.partner.id, 'name': 'x',
            })

    def test_an_editor_creates_and_edits_but_does_not_delete(self):
        doc = self.Document.with_user(self.editor).create({
            'name': 'By editor', 'kind': 'xlsx', 'res_model': 'res.partner', 'res_id': self.partner.id,
        })
        self.assertTrue(doc.can_edit)
        doc.write({'name': 'Renamed', 'author': 'Someone'})
        doc.action_archive()
        doc.action_unarchive()
        with self.assertRaises(AccessError):
            doc.unlink()
        # an Editor submits and opens new Revs, but neither approves nor deletes Revs
        with patch.object(type(self.Document), '_editor_is_open', lambda rec: False):
            doc.action_submit()
        with self.assertRaises(AccessError):
            doc.action_approve()
        doc.with_user(self.manager).action_approve()
        doc.action_new_revision('A change')
        self.assertEqual((doc.state, doc.revision, doc.version_count), ('draft', 2, 1))
        with self.assertRaises(AccessError):
            doc.action_delete_old_versions()
        with self.assertRaises(AccessError):
            doc.version_ids.action_delete()

    def test_a_manager_may_delete_documents_and_revs(self):
        doc = self._doc()
        as_manager = doc.with_user(self.manager)
        with patch.object(type(self.Document), '_editor_is_open', lambda rec: False):
            as_manager.action_submit()
        as_manager.action_approve()
        as_manager.action_new_revision('Again')
        with patch.object(type(self.Document), '_editor_is_open', lambda rec: False):
            as_manager.action_submit()
        as_manager.action_approve()
        self.assertEqual(doc.version_count, 2)
        self.assertEqual(as_manager.action_delete_old_versions()['tag'], 'display_notification')
        self.assertEqual(doc.version_ids.mapped('number'), [2])
        as_manager.unlink()  # a released document can be deleted by a Manager
        self.assertFalse(doc.exists())

    def test_an_editor_who_cannot_write_the_record_cannot_edit_its_documents(self):
        doc = self._doc()
        self.env['ir.rule'].create({
            'name': 'Acme is read only', 'model_id': self.env['ir.model']._get('res.partner').id,
            'domain_force': "[('name', '!=', 'Acme')]", 'groups': [(4, self.env.ref('base.group_user').id)],
            'perm_read': False, 'perm_create': False, 'perm_unlink': False,
        })
        self.assertFalse(doc.with_user(self.editor).can_edit)
        with self.assertRaises(AccessError):
            doc.with_user(self.editor).write({'name': 'Renamed'})

    # -- templates -----------------------------------------------------

    def test_a_template_keeps_the_file_it_was_made_from(self):
        template = self._template()
        self.assertEqual(template.kind, 'pptx')
        self.assertEqual(template.attachment_id.name, 'Company deck.pptx')
        self.assertEqual(template.attachment_id.raw, self.Document._blank_file('pptx'))
        self.assertEqual((template.attachment_id.res_model, template.attachment_id.res_id), ('jacon.office.template', template.id))
        self.assertFalse(template.upload)  # not kept a second time
        self.assertEqual(template.display_name, 'Company deck (PowerPoint)')

    def test_only_a_genuine_office_file_can_be_a_template(self):
        with self.assertRaises(UserError):
            self._template(upload=base64.b64encode(b'not an office file'))
        with self.assertRaises(UserError):
            self._template(upload=base64.b64encode(self.Document._blank_file('docx')), filename='wrong.pptx')
        with self.assertRaises(UserError):
            self._template(filename='notes.txt')
        with self.assertRaises(UserError):
            self.Template.create({'name': 'No file'})

    def test_a_templates_file_can_be_replaced_by_one_of_the_same_type(self):
        template = self._template()
        replacement = self.Document._blank_file('pptx') + b'extra'
        template.write({'upload': base64.b64encode(self.Document._blank_file('pptx')), 'upload_filename': 'newer.pptx'})
        self.assertEqual(template.kind, 'pptx')
        with self.assertRaises(UserError):
            template.write({'upload': base64.b64encode(self.Document._blank_file('docx')), 'upload_filename': 'other.docx'})
        self.assertTrue(replacement)

    def test_renaming_a_template_renames_its_file_and_names_are_unique(self):
        template = self._template()
        template.name = 'Renamed deck'
        self.assertEqual(template.attachment_id.name, 'Renamed deck.pptx')
        with self.assertRaises(Exception), self.cr.savepoint():
            self._template(name='RENAMED DECK')

    def test_templates_have_no_revs(self):
        template = self._template()
        template.attachment_id.sudo().write({'raw': self.Document._blank_file('pptx') + b'x'})
        self.assertFalse(self.env['jacon.office.document.version'].search([]))

    def test_a_template_can_be_copied_with_its_own_file(self):
        template = self._template()
        copy = template.copy()
        self.assertEqual(copy.name, 'Company deck (copy)')
        self.assertNotEqual(copy.attachment_id, template.attachment_id)
        self.assertEqual(copy.attachment_id.raw, template.attachment_id.raw)
        self.assertEqual(template.copy().name, 'Company deck (copy 2)')

    def test_the_name_of_a_copy_is_not_mistaken_for_one_with_wildcards(self):
        template = self._template(name='Q1_Report')
        self._template(name='QxReport (copy)')  # `_` is not a wildcard
        self.assertEqual(template.copy().name, 'Q1_Report (copy)')

    def test_an_archived_template_does_not_hold_its_name(self):
        template = self._template()
        template.active = False
        template.flush_recordset()
        self.assertTrue(self._template())

    def test_who_may_do_what_with_templates(self):
        template = self._template()
        self.assertEqual(template.with_user(self.viewer).name, 'Company deck')
        template.with_user(self.viewer).attachment_id.read(['raw'])
        with self.assertRaises(AccessError):
            template.with_user(self.viewer).write({'name': 'x'})
        self.Template.with_user(self.editor).create({
            'name': 'By editor', 'upload': base64.b64encode(self.Document._blank_file('docx')), 'upload_filename': 'a.docx',
        })
        # changing a template is for Managers: every new document starts from it
        with self.assertRaises(AccessError):
            template.with_user(self.editor).write({'description': 'edited'})
        with self.assertRaises(AccessError):
            template.attachment_id.with_user(self.editor).write({'raw': self.Document._blank_file('pptx') + b'x'})
        with self.assertRaises(AccessError):
            template.with_user(self.editor).unlink()
        self.assertFalse(template.with_user(self.editor).can_change)
        self.assertTrue(template.with_user(self.manager).can_change)
        template.with_user(self.manager).write({'description': 'edited'})
        attachment = template.attachment_id
        template.with_user(self.manager).unlink()
        self.assertFalse(attachment.exists())

    # -- starting a document from a template ---------------------------

    def _wizard(self, **vals):
        values = {'res_model': 'res.partner', 'res_id': self.partner.id}
        values.update(vals)
        return self.env['jacon.office.document.create.wizard'].create(values)

    def test_a_new_document_can_start_from_a_template(self):
        template = self._template()
        wizard = self._wizard(name='From the deck', template_id=template.id)
        wizard.action_create()
        doc = self.Document.search([('name', '=', 'From the deck')])
        self.assertEqual(doc.kind, 'pptx')
        self.assertEqual(doc.attachment_id.raw, template.attachment_id.raw)
        self.assertNotEqual(doc.attachment_id, template.attachment_id)
        # changing the document leaves the template alone
        doc.attachment_id.sudo().write({'raw': template.attachment_id.raw + b'x'})
        self.assertEqual(template.attachment_id.raw, self.Document._blank_file('pptx'))

    def test_a_blank_file_defaults_to_powerpoint(self):
        self._wizard(name='Plain').action_create()
        self.assertEqual(self.Document.search([('name', '=', 'Plain')]).kind, 'pptx')

    def test_an_uploaded_file_replaces_the_template(self):
        template = self._template()
        content = self.Document._blank_file('docx')
        wizard = self._wizard(
            name='Mine', template_id=template.id,
            upload=base64.b64encode(content), upload_filename='mine.docx',
        )
        wizard._onchange_upload()
        self.assertFalse(wizard.template_id)
        self.assertEqual(wizard.kind, 'docx')
        wizard.action_create()
        self.assertEqual(self.Document.search([('name', '=', 'Mine')]).attachment_id.raw, content)
        # choosing a template afterwards drops the uploaded file
        wizard = self._wizard(name='Back', template_id=template.id,
                              upload=base64.b64encode(content), upload_filename='mine.docx')
        wizard._onchange_template()
        self.assertFalse(wizard.upload)

    def test_a_category_with_a_template_starts_from_it(self):
        category = self.env.ref('jacon_office.category_specification')
        template = self._template(category_id=category.id)
        Wizard = self.env['jacon.office.document.create.wizard'].with_context(
            default_res_model='res.partner', default_res_id=self.partner.id,
        )
        defaults = Wizard.default_get(['template_id', 'category_id'])
        self.assertEqual(defaults['template_id'], template.id)
        # another category without a template: nothing is chosen for the user
        other = self.env.ref('jacon_office.category_report')
        wizard = self._wizard(category_id=other.id, template_id=False)
        wizard._onchange_category_template()
        self.assertFalse(wizard.template_id)
        wizard.category_id = category
        wizard._onchange_category_template()
        self.assertEqual(wizard.template_id, template)
