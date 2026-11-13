from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Every internal user is a Viewer, no longer an Editor by default, and Settings administrators are
    Managers.

    The data files say this too, but Odoo does not apply them when upgrading (the relations of
    `base.group_user` and `base.group_system` belong to the base module). Whoever already is an Editor
    stays one: removing what a group implies does not take anyone out of the group.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    viewer = env.ref('jacon_office.group_jacon_office_viewer')
    editor = env.ref('jacon_office.group_jacon_office_editor')
    manager = env.ref('jacon_office.group_jacon_office_manager')
    env.ref('base.group_user').write({'implied_ids': [(4, viewer.id), (3, editor.id)]})
    env.ref('base.group_system').write({'implied_ids': [(4, manager.id)]})
