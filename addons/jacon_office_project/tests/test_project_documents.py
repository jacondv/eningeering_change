from unittest.mock import patch

from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'jacon_office')
class TestProjectDocuments(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Document = cls.env['jacon.office.document']
        cls.project = cls.env['project.project'].create({'name': 'S45-268'})
        cls.other_project = cls.env['project.project'].create({'name': 'S45-300'})
        group_user = cls.env.ref('base.group_user')
        cls.project_user = cls.env['res.users'].create({
            'name': 'Project User', 'login': 'project_user',
            'group_ids': [(6, 0, [group_user.id, cls.env.ref('project.group_project_user').id])],
        })

    def test_the_new_document_dialog_starts_from_the_projects_name(self):
        action = self.project.action_new_office_document()
        self.assertEqual(action['res_model'], 'jacon.office.document.create.wizard')
        self.assertEqual(action['views'], [(False, 'form')])
        wizard = self.env['jacon.office.document.create.wizard'].with_context(**action['context']).create({})
        self.assertEqual(wizard.name, 'S45-268-Specification')
        wizard.action_create()
        self.assertEqual(self.project.office_document_count, 1)
        self.assertEqual(self.project.office_document_ids.name, 'S45-268-Specification')

    def test_a_project_only_counts_its_own_documents(self):
        self.Document.create({'name': 'A', 'kind': 'docx', 'res_model': 'project.project', 'res_id': self.project.id})
        self.Document.create({'name': 'B', 'kind': 'xlsx', 'res_model': 'project.project', 'res_id': self.other_project.id})
        self.assertEqual(self.project.office_document_ids.mapped('name'), ['A'])
        self.assertEqual(self.project.office_document_count, 1)

    def test_archived_documents_are_not_listed_or_counted(self):
        doc = self.Document.create({'name': 'A', 'kind': 'docx', 'res_model': 'project.project', 'res_id': self.project.id})
        doc.active = False
        self.assertFalse(self.project.office_document_ids)
        self.assertEqual(self.project.office_document_count, 0)

    def test_deleting_a_project_deletes_its_documents(self):
        doc = self.Document.create({'name': 'A', 'kind': 'docx', 'res_model': 'project.project', 'res_id': self.project.id})
        attachment = doc.attachment_id
        self.project.with_context(project_delete_password_confirmed=True).unlink()
        self.assertFalse(doc.exists())
        self.assertFalse(attachment.exists())

    def test_a_locked_project_refuses_new_documents_and_edits(self):
        doc = self.Document.create({'name': 'A', 'kind': 'docx', 'res_model': 'project.project', 'res_id': self.project.id})
        # What a Closed Project would answer.
        with patch.object(
            self.env.registry['project.project'], '_office_is_locked',
            new=lambda rec: rec.id == self.project.id,
        ):
            with self.assertRaises(UserError):
                self.Document.create({
                    'name': 'B', 'kind': 'docx', 'res_model': 'project.project', 'res_id': self.project.id,
                })
            with self.assertRaises(AccessError):
                doc.with_user(self.project_user).attachment_id.write({'raw': doc.attachment_id.raw})
