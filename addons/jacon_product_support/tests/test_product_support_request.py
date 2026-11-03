import base64

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestProductSupportRequestImages(TransactionCase):

    def test_every_html_field_adopts_orphaned_images(self):
        job = self.env['project.project'].create({'name': 'Job 1'})
        request = self.env['product.support.request'].create({
            'title': 'Image test', 'job_id': job.id, 'description': '<p>x</p>'})
        Attachment = self.env['ir.attachment'].sudo()
        for field_name in sorted(request.HTML_FIELDS):
            att = Attachment.create({
                'name': 'image.png', 'res_model': 'product.support.request', 'res_id': 0,
                'type': 'binary', 'datas': base64.b64encode(b'fake-png-bytes'),
                'mimetype': 'image/png',
            })
            request[field_name] = '<p>x</p><img src="/web/image/%d-abc123/image.png">' % att.id
            self.assertEqual(
                (att.res_model, att.res_id), ('product.support.request', request.id), field_name)

    def test_job_number_lists_ec_linked_through_support_request(self):
        job = self.env['project.project'].create({'name': 'Job 1'})
        change = self.env['engineering.change'].create({
            'title': 'From support', 'description': '<p>x</p>',
            # Not the test env's own user (inactive OdooBot): the default
            # Implement Team would drop it, failing the Implement Owner check.
            'engineer_id': self.env.ref('base.user_admin').id})
        self.assertFalse(job.engineering_change_ids)
        self.env['product.support.request'].create({
            'title': 'Linked', 'job_id': job.id, 'description': '<p>x</p>',
            'ec_id': change.id})
        job.invalidate_recordset(['engineering_change_ids'])
        self.assertEqual(job.engineering_change_ids, change)


@tagged('post_install', '-at_install')
class TestActionLinkToRequest(TransactionCase):

    def setUp(self):
        super().setUp()
        job = self.env['project.project'].create({'name': 'Job 1'})
        self.request = self.env['product.support.request'].create({
            'title': 'Link test', 'job_id': job.id, 'description': '<p>x</p>'})
        self.action = self.env['project.task'].create({
            'name': 'Action', 'support_request_id': self.request.id})

    def test_sub_task_joins_its_parents_request(self):
        child = self.env['project.task'].create({'name': 'Child', 'parent_id': self.action.id})

        self.assertEqual(child.support_request_id, self.request)
        self.assertEqual(child.project_id, self.request.project_id)
        self.assertIn(child, self.request.action_ids)

    def test_sub_task_created_from_the_parents_sub_tasks_action_joins_too(self):
        child = self.env['project.task'].with_context(
            default_parent_id=self.action.id).create({'name': 'Child'})

        self.assertEqual(child.support_request_id, self.request)

    def test_sub_task_of_a_plain_task_stays_unlinked(self):
        project = self.env['project.project'].create({'name': 'Plain'})
        parent = self.env['project.task'].create({'name': 'Parent', 'project_id': project.id})

        child = self.env['project.task'].create({'name': 'Child', 'parent_id': parent.id})

        self.assertFalse(child.support_request_id)
        self.assertEqual(child.project_id, project)

    def test_assignee_can_follow_the_action_back_to_its_request(self):
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Link Test', 'login': 'link_test',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        request, action = self.request, self.action
        action.user_ids = user

        Task = self.env['project.task'].with_user(user)
        arch = Task.get_view(self.env.ref('project.view_task_form2').id, 'form')['arch']
        self.assertIn('name="support_request_id"', arch)

        linked = Task.browse(action.id).support_request_id
        self.assertEqual(linked, request)
        self.assertEqual(linked.title, 'Link test')
