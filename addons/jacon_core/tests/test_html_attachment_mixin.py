import base64

from odoo.tests import TransactionCase, tagged


def img(att_id):
    return '<p>x</p><img src="/web/image/%d-abc123/image.png">' % att_id


@tagged('post_install', '-at_install')
class TestHtmlAttachmentMixin(TransactionCase):
    """jacon.html.attachment.mixin, exercised through project.task (the
    jacon_core model that uses it)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env['project.project'].create({'name': 'Mixin Test Project'})

    def _attachment(self, res_model, res_id=0, **extra):
        return self.env['ir.attachment'].sudo().create({
            'name': 'image.png', 'res_model': res_model, 'res_id': res_id,
            'type': 'binary', 'datas': base64.b64encode(b'fake-png-bytes'),
            'mimetype': 'image/png', **extra,
        })

    def _task(self, **vals):
        return self.env['project.task'].create({
            'name': 'Mixin Test Task', 'project_id': self.project.id, **vals})

    def test_create_adopts_orphan_uploaded_for_this_model(self):
        att = self._attachment('project.task')
        task = self._task(description=img(att.id))
        self.assertEqual((att.res_model, att.res_id), ('project.task', task.id))

    def test_write_adopts_orphan_uploaded_for_this_model(self):
        task = self._task()
        att = self._attachment('project.task')
        task.description = img(att.id)
        self.assertEqual((att.res_model, att.res_id), ('project.task', task.id))

    def test_media_library_image_is_not_adopted(self):
        # html_editor keeps shared Media Library / website images as
        # res_model='ir.ui.view', res_id=0 - adopting one would pull it out
        # of the library, and deleting the task would delete it everywhere.
        att = self._attachment('ir.ui.view', public=True)
        task = self._task(description=img(att.id))
        self.assertEqual((att.res_model, att.res_id), ('ir.ui.view', 0))
        task.unlink()
        self.assertTrue(att.exists())

    def test_orphan_uploaded_for_another_model_is_not_adopted(self):
        att = self._attachment('engineering.change')
        self._task(description=img(att.id))
        self.assertEqual((att.res_model, att.res_id), ('engineering.change', 0))

    def test_attachment_owned_by_another_record_is_not_hijacked(self):
        partner = self.env.user.partner_id
        att = self._attachment('res.partner', partner.id)
        self._task(description=img(att.id))
        self.assertEqual((att.res_model, att.res_id), ('res.partner', partner.id))

    def test_missing_image_warns_on_chatter(self):
        missing_id = 999999999
        self.assertFalse(self.env['ir.attachment'].browse(missing_id).exists())
        task = self._task(description=img(missing_id))
        self.assertTrue(any('could not be found' in (m.body or '') for m in task.message_ids))
