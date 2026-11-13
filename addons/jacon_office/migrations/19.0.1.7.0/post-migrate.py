def migrate(cr, version):
    """A document from before the workflow keeps the Revs of its saves, numbered 1..N: the Rev it is
    working on now (and the next it releases) comes after them."""
    cr.execute("""
        UPDATE jacon_office_document d
           SET revision = v.last_number + 1
          FROM (SELECT document_id, MAX(number) AS last_number
                  FROM jacon_office_document_version GROUP BY document_id) v
         WHERE v.document_id = d.id AND d.state = 'draft' AND d.revision <= v.last_number
    """)
