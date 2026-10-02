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
