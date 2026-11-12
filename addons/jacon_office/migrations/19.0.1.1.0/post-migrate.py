def migrate(cr, version):
    """Documents made before Revs existed: their author is who created them, and that is also
    who last edited them."""
    cr.execute("""
        UPDATE jacon_office_document
           SET author_id = COALESCE(author_id, create_uid),
               last_edit_user_id = COALESCE(last_edit_user_id, create_uid),
               last_edit_date = COALESCE(last_edit_date, create_date)
    """)
