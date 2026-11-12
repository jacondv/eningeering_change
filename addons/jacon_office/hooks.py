from odoo.addons.onlyoffice_odoo.utils import config_utils


def post_init_hook(env):
    """The connector makes its internal secret the first time it needs one, and committing while a
    PDF is being made would be wrong: make sure it exists now."""
    config_utils.get_internal_jwt_secret(env)
