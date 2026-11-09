def migrate(cr, version):
    """The first Revision History line is now "Initial release", not "Initial issue"."""
    cr.execute("""
        UPDATE qc_checksheet_history
           SET description = 'Initial release'
         WHERE description = 'Initial issue'
    """)
