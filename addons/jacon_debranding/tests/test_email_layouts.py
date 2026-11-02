from odoo.tests import TransactionCase, tagged, new_test_user

from ..models.res_config_settings import PARAM_PREFIX


@tagged('post_install', '-at_install')
class TestEmailLayouts(TransactionCase):
    """Emails render with a minimal QWeb context: `company` is there,
    `res_company` is not."""

    LAYOUTS = ('mail.mail_notification_light', 'mail.mail_notification_layout')

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(cls.env, login='debranding_user', email='debranding@example.com')

    def _render(self, layout):
        return self.env['mail.render.mixin'].with_context(
            email_notification_force_footer=True,
        )._render_encapsulate(layout, '<p>Body</p>', context_record=self.user)

    def _set_hidden(self, hidden):
        self.env['ir.config_parameter'].sudo().set_param(
            PARAM_PREFIX + 'hide_email_powered_by', 'True' if hidden else 'False')

    def test_powered_by_follows_the_switch(self):
        for layout in self.LAYOUTS:
            with self.subTest(layout=layout):
                self._set_hidden(True)
                self.assertNotIn('Powered by', self._render(layout))
                self._set_hidden(False)
                self.assertIn('Powered by', self._render(layout))

    def test_change_password_sends_security_email(self):
        """Regression: this used to raise KeyError: 'res_company'."""
        self._set_hidden(True)
        mails_before = self.env['mail.mail'].sudo().search_count([])
        self.user._change_password('a-new-password-1234')
        self.assertGreater(self.env['mail.mail'].sudo().search_count([]), mails_before)
