def migrate(cr, version):
    """Documents made before Revs existed: their author is who created them, and that is also
    who last edited them."""
    cr.execute("""
        UPDATE jacon_office_document
           SET author = COALESCE(author, (SELECT p.name FROM res_users u JOIN res_partner p ON p.id = u.partner_id
                                        WHERE u.id = jacon_office_document.create_uid)),
               last_edit_user_id = COALESCE(last_edit_user_id, create_uid),
               last_edit_date = COALESCE(last_edit_date, create_date)
    """)
