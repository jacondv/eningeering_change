"""Warranty "Unknown" was removed - an unset warranty is now simply empty."""


def migrate(cr, version):
    cr.execute("UPDATE product_support_request SET warranty = NULL WHERE warranty = 'unknown'")
