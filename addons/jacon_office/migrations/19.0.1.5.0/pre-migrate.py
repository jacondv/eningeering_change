def migrate(cr, version):
    """Office Documents has three levels now: Viewer, Editor, Manager. The old "User" group (which could
    create and edit) is the Editor: keep it, with the people who were in it."""
    cr.execute("""
        UPDATE ir_model_data SET name = 'group_jacon_office_editor'
         WHERE module = 'jacon_office' AND name = 'group_jacon_office_user' AND model = 'res.groups'
    """)
