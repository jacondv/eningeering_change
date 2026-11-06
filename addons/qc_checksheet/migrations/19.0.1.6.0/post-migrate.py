def migrate(cr, version):
    """Sheets already In Review before submitted_date existed: count their wait
    from their last change, so the Dashboard doesn't show them waiting 0 days."""
    cr.execute("""
        UPDATE qc_checksheet SET submitted_date = write_date
        WHERE state = 'review' AND submitted_date IS NULL
    """)
