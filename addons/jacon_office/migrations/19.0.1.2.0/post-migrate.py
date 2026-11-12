def migrate(cr, version):
    """PDFs are made when someone asks to view them, no longer by a cron: remove the cron."""
    cr.execute("""
        DELETE FROM ir_cron
         WHERE id IN (SELECT res_id FROM ir_model_data
                       WHERE module = 'jacon_office' AND name = 'ir_cron_convert_pdf' AND model = 'ir.cron')
    """)
    cr.execute("DELETE FROM ir_model_data WHERE module = 'jacon_office' AND name = 'ir_cron_convert_pdf'")
