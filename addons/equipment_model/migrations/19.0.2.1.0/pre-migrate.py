from odoo.exceptions import UserError


def migrate(cr, version):
    """Names become unique (ignoring case) from this version on. Say which ones
    are taken more than once, and by which records, rather than leave it to the
    bare database error the unique index would otherwise fail with."""
    duplicates = []
    for table, label in (
        ('equipment_model_category', 'Group'),
        ('equipment_model_family', 'Product Family'),
        ('equipment_model', 'Model'),
    ):
        cr.execute(f"""
            SELECT string_agg(name || ' (id ' || id || ')', ' / ' ORDER BY id)
              FROM {table}
             GROUP BY lower(name)
            HAVING count(*) > 1
             ORDER BY min(id)
        """)
        duplicates += [f"{label} {spellings}" for (spellings,) in cr.fetchall()]
    if duplicates:
        raise UserError(
            f"Equipment Model names must be unique before this update. {len(duplicates)} taken twice. "
            "Rename or merge them, then update again:\n- " + "\n- ".join(duplicates))
