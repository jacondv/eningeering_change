import base64

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestBulletinSectionImages(TransactionCase):

    def test_content_adopts_orphaned_image(self):
        section = self.env['bulletin.section'].create({'name': 'Body'})
        template = self.env['bulletin.template'].create({'name': 'Template'})
        bulletin = self.env['bulletin.bulletin'].create({'template_id': template.id})
        line = self.env['bulletin.bulletin.section'].create({
            'bulletin_id': bulletin.id, 'section_id': section.id})
        att = self.env['ir.attachment'].sudo().create({
            'name': 'image.png', 'res_model': 'bulletin.bulletin.section', 'res_id': 0,
            'type': 'binary', 'datas': base64.b64encode(b'fake-png-bytes'),
            'mimetype': 'image/png',
        })
        line.content = '<p>x</p><img src="/web/image/%d-abc123/image.png">' % att.id
        self.assertEqual((att.res_model, att.res_id), ('bulletin.bulletin.section', line.id))
