from odoo import http
from odoo.http import request


class EngineeringChangeController(http.Controller):

    @http.route('/engineering_change/<int:change_id>/send_email', type='http', auth='user')
    def send_email(self, change_id):
        """Redirects to a mailto: link for this request.

        Exists only because ir.actions.act_url can't target a non-http(s)
        URL directly: the web client prefixes a "/" onto any url that
        doesn't already start with "http" or "/" (see
        _executeActURLAction in action_service.js), turning "mailto:..."
        into a broken internal route ("/mailto:...", a 404) regardless of
        target ('self' or 'new'). Routing action_send_email() through a
        real HTTP endpoint that issues an actual redirect sidesteps that
        entirely - the browser/OS then handles the mailto: scheme itself,
        same as any other 303 redirect to an external scheme.
        """
        change = request.env['engineering.change'].browse(change_id)
        change.check_access('read')
        return request.redirect(change._get_send_email_mailto_url(), local=False)
