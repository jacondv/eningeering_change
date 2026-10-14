from .models.res_config_settings import PARAM_PREFIX, PUBLISHER_CRON_XMLID

# Hidden straight away on install; "Manage Databases" and the tab title are
# left as they are until an admin switches them in Settings.
HIDDEN_BY_DEFAULT = (
    'hide_odoo_account',
    'hide_help',
    'hide_login_powered_by',
    'hide_email_powered_by',
    'hide_portal_powered_by',
    'disable_publisher',
)


def post_init_hook(env):
    params = env['ir.config_parameter'].sudo()
    for key in HIDDEN_BY_DEFAULT:
        params.set_param(PARAM_PREFIX + key, 'True')
    cron = env.ref(PUBLISHER_CRON_XMLID, raise_if_not_found=False)
    if cron:
        cron.sudo().active = False


def uninstall_hook(env):
    """Back to plain Odoo: the settings go away with the module, and the
    Publisher call it switched off runs again."""
    env['ir.config_parameter'].sudo().search([('key', '=like', PARAM_PREFIX + '%')]).unlink()
    cron = env.ref(PUBLISHER_CRON_XMLID, raise_if_not_found=False)
    if cron:
        cron.sudo().active = True
