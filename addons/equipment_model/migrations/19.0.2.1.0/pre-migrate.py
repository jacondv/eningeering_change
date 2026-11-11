def migrate(cr, version):
    """Names become unique (ignoring case) from this version on. Say which ones
    are taken twice, rather than leave it to the bare database error the
    unique index would otherwise fail with."""
    duplicates = []
    for table, label in (
        ('equipment_model_category', 'Group'),
        ('equipment_model_family', 'Product Family'),
        ('equipment_model', 'Model'),
    ):
        cr.execute(f"SELECT min(name) FROM {table} GROUP BY lower(name) HAVING count(*) > 1 ORDER BY 1")
        duplicates += [f"{label} {name}" for (name,) in cr.fetchall()]
    if duplicates:
        raise Exception(
            "Equipment Model names must be unique before this update. Rename or merge these, "
            f"then update again ({len(duplicates)}): " + ", ".join(duplicates))
