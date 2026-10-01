import logging

from odoo import SUPERUSER_ID, api

from odoo.addons.part_number_manager.models.part_number import PRODUCT_CREATE_CONTEXT, VENDOR_FIELDS

_logger = logging.getLogger(__name__)

BATCH_SIZE = 1000


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, dict(PRODUCT_CREATE_CONTEXT, active_test=False))
    part_model = env['part_number_manager.part_number']
    seller_model = env['product.supplierinfo']
    unknown_vendor = env.ref('part_number_manager.partner_unknown_vendor')
    company_currency_id = env.company.currency_id.id

    cr.execute("""
        SELECT id, vendor_id, vendor_ref, reference_price, currency_id, lead_time
        FROM pnm_mig_vendor_backup ORDER BY id
    """)
    rows = cr.dictfetchall()
    _logger.info('Moving Vendor data of %s Part(s) to product.supplierinfo', len(rows))

    for start in range(0, len(rows), BATCH_SIZE):
        batch = rows[start:start + BATCH_SIZE]
        parts = part_model.browse([row['id'] for row in batch])
        parts._ensure_product()
        seller_model.create([{
            'product_tmpl_id': part.product_id.product_tmpl_id.id,
            'partner_id': row['vendor_id'] or unknown_vendor.id,
            'product_code': row['vendor_ref'] or False,
            'price': row['reference_price'] or 0.0,
            'currency_id': row['currency_id'] or company_currency_id,
            'delay': (row['lead_time'] or 0) * 7,
        } for part, row in zip(parts, batch)])
        env.flush_all()
        env.invalidate_all()
        _logger.info('  %s/%s done', min(start + BATCH_SIZE, len(rows)), len(rows))

    # The Part's stored Vendor fields now mirror the new Vendor lines.
    parts = part_model.browse([row['id'] for row in rows])
    for fname in VENDOR_FIELDS:
        env.add_to_compute(part_model._fields[fname], parts)
    env.flush_all()

    _verify(cr, unknown_vendor.id, company_currency_id)


def _verify(cr, unknown_vendor_id, company_currency_id):
    """Any mismatch raises, rolling the whole upgrade back."""
    checks = {
        'Part with Vendor data but no product': """
            SELECT count(*) FROM pnm_mig_vendor_backup b
            JOIN part_number_manager_part_number p ON p.id = b.id
            WHERE p.product_id IS NULL
        """,
        'Part without exactly one Vendor line': """
            SELECT count(*) FROM pnm_mig_vendor_backup b
            JOIN part_number_manager_part_number p ON p.id = b.id
            JOIN product_product pp ON pp.id = p.product_id
            WHERE (SELECT count(*) FROM product_supplierinfo s WHERE s.product_tmpl_id = pp.product_tmpl_id) <> 1
        """,
        'Part Vendor fields differ from backup': """
            SELECT count(*) FROM pnm_mig_vendor_backup b
            JOIN part_number_manager_part_number p ON p.id = b.id
            WHERE p.vendor_id IS DISTINCT FROM COALESCE(b.vendor_id, %(unknown)s)
               OR COALESCE(p.vendor_ref, '') <> COALESCE(b.vendor_ref, '')
               OR abs(COALESCE(p.reference_price, 0) - COALESCE(b.reference_price, 0)) >= 0.005
               OR p.currency_id IS DISTINCT FROM COALESCE(b.currency_id, %(currency)s)
               OR COALESCE(p.lead_time, 0) <> COALESCE(b.lead_time, 0)
        """,
        'Product Internal Reference differs from Part Number': """
            SELECT count(*) FROM part_number_manager_part_number p
            JOIN product_product pp ON pp.id = p.product_id
            WHERE pp.default_code IS DISTINCT FROM NULLIF(p.part_number, '')
        """,
        'Part product saleable or purchasable': """
            SELECT count(*) FROM part_number_manager_part_number p
            JOIN product_product pp ON pp.id = p.product_id
            JOIN product_template t ON t.id = pp.product_tmpl_id
            WHERE t.sale_ok OR t.purchase_ok
        """,
    }
    failures = []
    for label, query in checks.items():
        cr.execute(query, {'unknown': unknown_vendor_id, 'currency': company_currency_id})
        count = cr.fetchone()[0]
        _logger.info('Verify - %s: %s', label, count)
        if count:
            failures.append(f'{label}: {count}')
    if failures:
        raise RuntimeError('part_number_manager migration verification failed - ' + '; '.join(failures))
