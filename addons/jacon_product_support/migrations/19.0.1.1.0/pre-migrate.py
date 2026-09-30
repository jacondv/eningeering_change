"""Diagnosing / Guiding-Repairing stages were removed, and the Customer
Confirmation checkbox was replaced by the confirmation date alone."""


def migrate(cr, version):
    cr.execute("""
        UPDATE product_support_request
           SET state = 'draft'
         WHERE state IN ('diagnosing', 'repairing')
    """)
    cr.execute("""
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'product_support_request' AND column_name = 'customer_confirmed'
    """)
    if cr.fetchone():
        # A ticked box without a date would now read as "not confirmed".
        cr.execute("""
            UPDATE product_support_request
               SET customer_confirmed_date = write_date::date
             WHERE customer_confirmed AND customer_confirmed_date IS NULL
        """)
        cr.execute("""
            UPDATE product_support_request
               SET customer_confirmed_date = NULL
             WHERE NOT COALESCE(customer_confirmed, FALSE)
        """)
