from odoo import SUPERUSER_ID, api


def grant_view_to_current_users(env):
    """Everyone who is already an internal user can view the documents (View is the default level; a
    Manager of the users can set a person to no access afterwards)."""
    env = api.Environment(env.cr, SUPERUSER_ID, {})
    group = env.ref('part_number_docs.group_pnd_view')
    env['res.users'].with_context(active_test=False).search([('share', '=', False)]).write(
        {'group_ids': [(4, group.id)]},
    )
