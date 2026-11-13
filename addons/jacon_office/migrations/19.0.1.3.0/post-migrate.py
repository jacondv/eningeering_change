def migrate(cr, version):
    """The author became free text: keep the name of the user it used to point to."""
    cr.execute("""
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'jacon_office_document' AND column_name = 'author_id'
    """)
    if cr.fetchone():
        cr.execute("""
            UPDATE jacon_office_document d
               SET author = p.name
              FROM res_users u JOIN res_partner p ON p.id = u.partner_id
             WHERE u.id = d.author_id AND d.author IS NULL
        """)
