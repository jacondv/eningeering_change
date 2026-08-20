from odoo import _, fields, models
from odoo.exceptions import AccessDenied, UserError


class JaconDeletePasswordWizard(models.TransientModel):
    """Always asks for the current user's own password before permanently
    deleting a record, regardless of how recently they last typed it.

    Deliberately does NOT use the core `check_identity` decorator: that
    caches a successful check for 10 minutes (`identity-check-last` in the
    session), so a second delete shortly after the first would skip the
    prompt entirely - not what's wanted for an irreversible action like this.
    Verifying the password manually here, on every single confirm, avoids
    that cache.
    """
    _name = 'jacon.delete.password.wizard'
    _description = 'Confirm Password Before Delete'

    res_model = fields.Char(required=True)
    res_id = fields.Integer(required=True)
    redirect_action_xmlid = fields.Char(
        required=True,
        help="Loaded after deletion instead of trying to reload the "
             "now-deleted record's form - e.g. 'module.action_xml_id'.")
    password = fields.Char(required=True)

    def action_confirm_delete(self):
        self.ensure_one()
        credential = {'login': self.env.user.login, 'password': self.password, 'type': 'password'}
        try:
            self.env.user._check_credentials(credential, {'interactive': True})
        except AccessDenied:
            raise UserError(_("Incorrect password."))
        record = self.env[self.res_model].browse(self.res_id)
        record.with_context(
            ec_delete_password_confirmed=True,
            project_delete_password_confirmed=True,
        ).unlink()
        return self.env['ir.actions.act_window']._for_xml_id(self.redirect_action_xmlid)
