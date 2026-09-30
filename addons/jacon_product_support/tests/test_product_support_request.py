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
