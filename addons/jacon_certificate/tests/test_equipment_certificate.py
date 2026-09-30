import base64

from odoo.tests import TransactionCase, tagged


def img(att_id):
    return '<p>x</p><img src="/web/image/%d-abc123/image.png">' % att_id


@tagged('post_install', '-at_install')
class TestEquipmentCertificateImages(TransactionCase):

    def test_description_adopts_orphaned_image(self):
        att = self.env['ir.attachment'].sudo().create({
            'name': 'image.png', 'res_model': 'equipment.certificate', 'res_id': 0,
            'type': 'binary', 'datas': base64.b64encode(b'fake-png-bytes'),
            'mimetype': 'image/png',
        })
        cert = self.env['equipment.certificate'].create({'name': 'Cert'})
        cert.description = img(att.id)
        self.assertEqual((att.res_model, att.res_id), ('equipment.certificate', cert.id))

    def test_missing_image_is_logged_without_chatter(self):
        # No mail.thread on this model - the warning goes to the server log.
        with self.assertLogs('odoo.addons.jacon_core.models.jacon_html_attachment_mixin',
                             level='WARNING') as logs:
            self.env['equipment.certificate'].create({
                'name': 'Cert', 'description': img(999999999)})
        self.assertIn('999999999', logs.output[0])
