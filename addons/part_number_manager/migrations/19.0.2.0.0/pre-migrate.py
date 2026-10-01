import logging

_logger = logging.getLogger(__name__)

VENDOR_DATA_SQL = """
    vendor_id IS NOT NULL
    OR COALESCE(vendor_ref, '') <> ''
    OR COALESCE(reference_price, 0) <> 0
    OR COALESCE(lead_time, 0) <> 0
"""


def migrate(cr, version):
    # Make = produced in-house: such Parts must not carry Vendor data any
    # more. They are fixed by hand before upgrading - stop here (rolling the
    # whole upgrade back) if any are left, rather than migrate bad data.
    cr.execute(f"""
        SELECT COALESCE(part_number, '#' || id) FROM part_number_manager_part_number
        WHERE make_buy = 'make' AND ({VENDOR_DATA_SQL}) ORDER BY 1
    """)
    leftovers = [row[0] for row in cr.fetchall()]
    if leftovers:
        raise RuntimeError(
            'part_number_manager upgrade aborted: %s Make Part(s) still have Vendor data - fix them first: %s'
            % (len(leftovers), ', '.join(leftovers)))

    # The five Vendor fields become a mirror of product.supplierinfo; their
    # current values are copied aside first, both as the migration's source
    # and to verify against afterwards (dropped by hand weeks later).
    cr.execute('DROP TABLE IF EXISTS pnm_mig_vendor_backup')
    cr.execute(f"""
        CREATE TABLE pnm_mig_vendor_backup AS
        SELECT id, vendor_id, vendor_ref, reference_price, currency_id, lead_time
        FROM part_number_manager_part_number
        WHERE {VENDOR_DATA_SQL}
    """)
    cr.execute('SELECT count(*) FROM pnm_mig_vendor_backup')
    _logger.info('pnm_mig_vendor_backup: %s Part(s) with Vendor data backed up', cr.fetchone()[0])
