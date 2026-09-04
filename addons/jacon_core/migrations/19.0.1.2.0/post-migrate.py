def migrate(cr, version):
    """Runs automatically on any machine upgrading jacon_core past this
    version (Odoo's standard migrations/<version>/post-migrate.py hook -
    unlike post_init_hook, this DOES fire for an already-installed module
    being upgraded, which is the actual production scenario). See
    migrate_last_update_status in __init__.py (used for a brand new
    install instead) for why this is needed: models/project_project.py and
    models/project_update.py restrict last_update_status/status to just
    in_progress/on_hold/cancelled/eol, so any row still holding one of
    core's old on_track/at_risk/off_track/done/to_define values is moved
    to 'in_progress'.
    """
    cr.execute("""
        UPDATE project_update SET status = 'in_progress'
        WHERE status IN ('on_track', 'at_risk', 'off_track', 'done')
    """)
    cr.execute("""
        UPDATE project_project SET last_update_status = 'in_progress'
        WHERE last_update_status IN ('to_define', 'on_track', 'at_risk', 'off_track', 'done')
    """)
