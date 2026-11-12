def migrate(cr, version):
    """PDFs are now PDF/A (plain PDFs lost gradient fills in many viewers): the ones already made
    are made again the next time someone views them."""
    cr.execute("UPDATE jacon_office_document SET pdf_state = 'pending', pdf_checksum = NULL WHERE pdf_attachment_id IS NOT NULL")
