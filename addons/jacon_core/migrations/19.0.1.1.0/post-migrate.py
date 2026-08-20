def migrate(cr, version):
    """Backfill Start Date for tasks created before this field existed.

    `date_start`'s `default=` only applies to new records - it never
    backfilled the ones already in the database when the field was
    added, so any task created before that point still has NULL here.
    Left NULL, hr.employee._simulate_schedule falls back to treating the
    task as starting on its own deadline day (dumping all of its
    allocated_hours onto that single day), which can make an old task's
    deadline look artificially, drastically overloaded. create_date is
    the closest real fact we have to what its Start Date would have
    defaulted to at the time (context_today() on creation).
    """
    cr.execute("""
        UPDATE project_task
        SET date_start = create_date::date
        WHERE date_start IS NULL
    """)
