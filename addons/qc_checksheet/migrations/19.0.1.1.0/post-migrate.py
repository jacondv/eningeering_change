"""Moves check sheets made before Revisions existed onto the new workflow, as
Draft Rev 0, so they can be finished or deleted, and hands out the new default
Create & Edit access, since group_qc_user is now view-only. post_init_hook only
runs on a fresh install, so already-installed databases need this instead.
"""
from odoo import SUPERUSER_ID, api
from odoo.addons.qc_checksheet.hooks import grant_default_access

LINE_TABLES = (
    'qc_checksheet_group',
    'qc_checksheet_item',
    'qc_checksheet_panel_line',
    'qc_checksheet_image_group',
    'qc_checksheet_image_line',
)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    grant_default_access(env)

    cr.execute("""
        UPDATE qc_checksheet
           SET state = COALESCE(state, 'draft'),
               revision = COALESCE(revision, 0),
               root_id = COALESCE(root_id, id)
    """)
    for xmlid, layout in (
        ('qc_checksheet.checksheet_type_general', 'standard'),
        ('qc_checksheet.checksheet_type_panel_sticker', 'panel_sticker'),
    ):
        cr.execute(
            "UPDATE qc_checksheet SET type_id = %s WHERE type_id IS NULL AND checksheet_type = %s",
            (env.ref(xmlid).id, layout),
        )
    # Each row needs its own key, which a field default can't give existing rows.
    for table in LINE_TABLES:
        cr.execute(f"UPDATE {table} SET line_key = md5(random()::text || id::text) WHERE line_key IS NULL")
    env.registry.clear_cache()
