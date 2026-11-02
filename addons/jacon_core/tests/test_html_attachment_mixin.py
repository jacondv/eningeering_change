import base64
from unittest.mock import patch

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

    # ------------------------------------------------------------------
    # An image pasted from another record gets its own copy
    # ------------------------------------------------------------------

    def _pasted(self, att, suffix=''):
        return '<p><img src="/web/image/%d-%s/image.png%s"></p>' % (att.id, att.checksum[:8], suffix)

    def _borrowed_image(self):
        source = self._task()
        return source, self._attachment('project.task', source.id)

    def _own_images(self, task):
        return self.env['ir.attachment'].sudo().search([
            ('res_model', '=', 'project.task'), ('res_id', '=', task.id)])

    def test_pasted_image_survives_deleting_its_source_record(self):
        source, att = self._borrowed_image()
        checksum = att.checksum
        target = self._task(description=self._pasted(att))

        source.unlink()

        self.assertFalse(att.exists())
        image = self._own_images(target)
        self.assertEqual(len(image), 1)
        self.assertEqual(image.checksum, checksum)
        self.assertIn(f'/web/image/{image.id}-', target.description)
        self.assertIn(f'access_token={image.access_token}', target.description)

    def test_write_copies_a_pasted_image_and_leaves_the_source_alone(self):
        source, att = self._borrowed_image()
        target = self._task()

        target.description = self._pasted(att)

        image = self._own_images(target)
        self.assertEqual(len(image), 1)
        self.assertNotEqual(image, att)
        self.assertEqual(image.store_fname, att.store_fname)
        self.assertEqual((att.res_model, att.res_id), ('project.task', source.id))
        self.assertNotIn(f'/web/image/{att.id}-', target.description)

    def test_absolute_src_is_copied_too(self):
        # What the editor's copy actually puts on the clipboard.
        _source, att = self._borrowed_image()

        target = self._task(description=(
            f'<p><img src="http://localhost:8069/web/image/{att.id}-{att.checksum[:8]}/image.png"></p>'))

        image = self._own_images(target)
        self.assertEqual(len(image), 1)
        self.assertNotIn(f'/web/image/{att.id}-', target.description)
        self.assertIn(f'src="/web/image/{image.id}-', target.description)

    def test_copy_gets_its_own_access_token(self):
        _source, att = self._borrowed_image()
        att.generate_access_token()

        target = self._task(description=self._pasted(att))

        self.assertNotEqual(self._own_images(target).access_token, att.access_token)

    def test_image_pasted_twice_is_copied_once_and_saving_again_adds_none(self):
        _source, att = self._borrowed_image()
        target = self._task(description=self._pasted(att) + self._pasted(att))
        image = self._own_images(target)
        self.assertEqual(len(image), 1)
        self.assertEqual(target.description.count(f'/web/image/{image.id}-'), 2)

        target.description = target.description + '<p>more</p>'

        self.assertEqual(self._own_images(target), image)

    def test_each_record_of_a_batch_gets_its_own_copy(self):
        _source, att = self._borrowed_image()
        first, second = self._task(), self._task()

        (first | second).write({'description': self._pasted(att)})

        self.assertNotEqual(self._own_images(first), self._own_images(second))
        self.assertEqual(len(self._own_images(first)), 1)
        self.assertEqual(len(self._own_images(second)), 1)

    def test_image_uploaded_for_another_model_is_copied_too(self):
        # Pasted out of a form that hasn't been saved yet: nothing owns it,
        # and it'd be vacuumed if that form never gets saved.
        att = self._attachment('engineering.change')

        target = self._task(description=self._pasted(att))

        self.assertEqual(len(self._own_images(target)), 1)
        self.assertEqual((att.res_model, att.res_id), ('engineering.change', 0))

    def test_copying_a_record_gives_the_copy_its_own_images(self):
        original = self._task()
        att = self._attachment('project.task', original.id)
        original.description = self._pasted(att)

        duplicate = original.copy()

        self.assertNotIn(f'/web/image/{att.id}-', duplicate.description)

    def test_own_image_is_left_as_is(self):
        task = self._task()
        att = self._attachment('project.task', task.id)
        content = self._pasted(att)

        task.description = content

        self.assertEqual(self._own_images(task), att)
        self.assertIn(f'/web/image/{att.id}-', task.description)

    def test_media_library_image_is_not_copied(self):
        att = self._attachment('ir.ui.view', public=True)

        task = self._task(description=self._pasted(att))

        self.assertFalse(self._own_images(task))
        self.assertIn(f'/web/image/{att.id}-', task.description)

    def test_src_with_the_wrong_checksum_is_not_copied(self):
        # Its id may well mean something else by now: don't copy "that".
        _source, att = self._borrowed_image()
        wrong = 'ffffffff' if att.checksum[:8] != 'ffffffff' else '00000000'

        task = self._task(description=f'<p><img src="/web/image/{att.id}-{wrong}/image.png"></p>')

        self.assertFalse(self._own_images(task))

    def _private_attachment(self):
        # Attached to a record only system admins can read.
        param = self.env['ir.config_parameter'].sudo().search([], limit=1)
        return self._attachment('ir.config_parameter', param.id)

    def _project_user(self):
        return self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Mixin Test User', 'login': 'mixin_test_user',
            'group_ids': [(6, 0, [self.env.ref('project.group_project_manager').id])],
        })

    def test_image_the_user_cannot_read_is_not_copied(self):
        att = self._private_attachment()
        user = self._project_user()
        self.assertFalse(self.env['ir.attachment'].with_user(user).browse(att.id).has_access('read'))

        task = self._task().with_user(user)
        task.description = self._pasted(att)

        self.assertFalse(self._own_images(task))

    def test_image_the_user_holds_a_token_for_is_copied(self):
        att = self._private_attachment()
        att.generate_access_token()
        user = self._project_user()

        task = self._task().with_user(user)
        task.description = self._pasted(att, f'?access_token={att.access_token}')

        self.assertEqual(len(self._own_images(task)), 1)

    def test_wrong_token_does_not_stand_in_for_read_access(self):
        att = self._private_attachment()
        att.generate_access_token()
        user = self._project_user()

        task = self._task().with_user(user)
        task.description = self._pasted(att, '?access_token=not-the-token')

        self.assertFalse(self._own_images(task))

    def test_swapping_the_src_is_not_logged_as_a_second_change(self):
        _source, att = self._borrowed_image()
        target = self._task()
        Log = self.env['jacon.field.change.log'].sudo()

        with patch.object(type(target), '_notify_description_change') as notify:
            target.description = self._pasted(att)

        logs = Log.search([('res_model', '=', 'project.task'), ('res_id', '=', target.id)])
        self.assertEqual(len(logs), 1)
        # What's logged is the image the task actually ended up with.
        self.assertIn(f'/web/image/{self._own_images(target).id}-', logs.diff)
        notify.assert_called_once()
