from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPartProductLink(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        category = cls.env['part_number_manager.material_category'].create({'code': '99', 'description': 'Test'})
        cls.group = cls.env['part_number_manager.material_group'].create(
            {'code': '9901', 'description': 'Test Group', 'category_id': category.id})
        cls.vendor = cls.env['res.partner'].create({'name': 'ACME Supplies', 'ref': 'V-ACME'})
        cls.usd = cls.env.ref('base.USD')
        cls.Part = cls.env['part_number_manager.part_number'].with_context(skip_job_number_check=True)
        cls.unknown_vendor = cls.env.ref('part_number_manager.partner_unknown_vendor')

    def _part(self, number, **vals):
        return self.Part.create(dict({
            'material_group_id': self.group.id,
            'part_number': number,
            'sequence_suffix': number[-4:],
            'short_description': f'Desc {number}',
        }, **vals))

    def test_no_vendor_data_no_product(self):
        part = self._part('99010001', make_buy='buy')
        self.assertFalse(part.product_id)

    def test_vendor_data_creates_product_and_vendor_line(self):
        part = self._part('99010002', make_buy='buy', vendor_id=self.vendor.id, vendor_ref='ACME-123',
                          reference_price=12.5, currency_id=self.usd.id, lead_time=3)
        product = part.product_id
        self.assertTrue(product)
        self.assertEqual(product.default_code, '99010002')
        self.assertEqual(product.name, 'Desc 99010002')
        self.assertFalse(product.sale_ok)
        self.assertFalse(product.purchase_ok)
        seller = product.product_tmpl_id.variant_seller_ids
        self.assertEqual(len(seller), 1)
        self.assertEqual(seller.partner_id, self.vendor)
        self.assertEqual(seller.product_code, 'ACME-123')
        self.assertEqual(seller.price, 12.5)
        self.assertEqual(seller.currency_id, self.usd)
        self.assertEqual(seller.delay, 21)
        # Values read back on the Part are unchanged by the round trip.
        self.assertEqual(part.vendor_id, self.vendor)
        self.assertEqual(part.vendor_ref, 'ACME-123')
        self.assertEqual(part.reference_price, 12.5)
        self.assertEqual(part.lead_time, 3)

    def test_vendor_ref_without_vendor_uses_unknown_vendor(self):
        part = self._part('99010003', make_buy='buy', vendor_ref='NOVENDOR-1')
        self.assertEqual(part.product_id.product_tmpl_id.variant_seller_ids.partner_id, self.unknown_vendor)
        self.assertEqual(part.vendor_id, self.unknown_vendor)

    def test_edit_vendor_fields_updates_single_line(self):
        part = self._part('99010004', make_buy='buy', vendor_id=self.vendor.id, vendor_ref='A')
        part.write({'vendor_ref': 'B', 'reference_price': 5.0, 'lead_time': 2})
        sellers = part.product_id.product_tmpl_id.variant_seller_ids
        self.assertEqual(len(sellers), 1)
        self.assertEqual((sellers.product_code, sellers.price, sellers.delay), ('B', 5.0, 14))

    def test_lead_time_rounds_up_from_days(self):
        part = self._part('99010005', make_buy='buy', vendor_id=self.vendor.id)
        part.product_id.product_tmpl_id.variant_seller_ids.delay = 10
        self.assertEqual(part.lead_time, 2)

    def test_part_changes_sync_to_product(self):
        part = self._part('99010006', make_buy='buy', vendor_id=self.vendor.id)
        part.write({'short_description': 'Renamed', 'long_description': 'Long text'})
        self.assertEqual(part.product_id.name, 'Renamed')
        self.assertEqual(part.product_id.description_purchase, 'Long text')

    def test_archive_and_unarchive_follow_part(self):
        part = self._part('99010007', make_buy='buy', vendor_id=self.vendor.id)
        template = part.product_id.product_tmpl_id
        part.action_archive()
        self.assertFalse(part.product_id.active)
        self.assertFalse(template.active)
        part.action_unarchive()
        self.assertTrue(part.product_id.active)
        self.assertTrue(template.active)

    def test_switch_to_make_removes_vendor_data(self):
        part = self._part('99010008', make_buy='buy', vendor_id=self.vendor.id, vendor_ref='X')
        product = part.product_id
        part.make_buy = 'make'
        self.assertEqual(part.product_id, product, 'Product is kept')
        self.assertFalse(product.product_tmpl_id.variant_seller_ids)
        self.assertFalse(part.vendor_id)
        self.assertFalse(part.vendor_ref)
        self.assertIn('Vendor data removed', part.message_ids[:1].body)

    def test_make_part_cannot_get_vendor_data(self):
        part = self._part('99010009', make_buy='make')
        with self.assertRaises(ValidationError):
            part.vendor_id = self.vendor

    def test_create_link_product_reuses_matching_code(self):
        existing = self.env['product.product'].create({'name': 'Pre-existing', 'default_code': '99010010'})
        part = self._part('99010010', make_buy='make')
        part.action_create_link_product()
        self.assertEqual(part.product_id, existing)
        self.assertEqual(existing.name, 'Desc 99010010')

    def test_create_link_product_creates_when_missing(self):
        part = self._part('99010011', make_buy='make')
        part.action_create_link_product()
        self.assertEqual(part.product_id.default_code, '99010011')
        with self.assertRaises(UserError):
            part.action_create_link_product()

    def test_product_side_cannot_change_internal_reference(self):
        part = self._part('99010012', make_buy='buy', vendor_id=self.vendor.id)
        with self.assertRaises(UserError):
            part.product_id.default_code = 'OTHER'
        part.write({'part_number': '99010099'})
        self.assertEqual(part.product_id.default_code, '99010099')

    def test_unlink_part_removes_unused_product(self):
        part = self._part('99010013', make_buy='buy', vendor_id=self.vendor.id)
        product = part.product_id
        part.unlink()
        self.assertFalse(product.exists())

    def test_search_vendor_ref_across_all_vendors(self):
        part = self._part('99010014', make_buy='buy', vendor_id=self.vendor.id, vendor_ref='MAIN-1')
        self.env['product.supplierinfo'].create({
            'product_tmpl_id': part.product_id.product_tmpl_id.id,
            'partner_id': self.unknown_vendor.id,
            'product_code': 'SECOND-1',
            'sequence': 99,
        })
        self.assertEqual(self.Part.search([('all_vendor_refs', 'ilike', 'SECOND-1')]), part)
        self.assertEqual(self.Part.find_duplicate_vendor_refs(['SECOND-1']), {'SECOND-1': ['99010014']})
        self.assertEqual(part.vendor_ref, 'MAIN-1', 'Main Vendor is still the lowest sequence')

    def test_batch_create_with_generated_number_saves_vendor(self):
        result = self.Part.create_batch_with_generated_number([{
            'material_group_id': self.group.id,
            'job_number': self.env['project.project'].create({'name': 'PNM Test Job'}).id,
            'short_description': 'From page',
            'make_buy': 'buy',
            'vendor_name': 'Brand New Vendor',
            'vendor_ref': 'PAGE-1',
        }])
        self.assertTrue(result[0]['success'], result[0]['error'])
        part = self.Part.browse(result[0]['part_id'])
        self.assertEqual(part.vendor_id.name, 'Brand New Vendor')
        self.assertEqual(part.product_id.product_tmpl_id.variant_seller_ids.product_code, 'PAGE-1')


@tagged('post_install', '-at_install')
class TestVendorCodeName(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Partner = cls.env['res.partner']
        cls.both = cls.Partner.create({'name': 'Cong Ty ABC', 'ref': '10293442'})
        cls.name_only = cls.Partner.create({'name': 'Name Only Co'})

    def _label(self, partner):
        return partner.with_context(pnm_vendor_display=True).display_name

    def test_label_formats(self):
        self.assertEqual(self._label(self.both), '10293442 - Cong Ty ABC')
        self.assertEqual(self._label(self.name_only), 'Name Only Co')
        code_only = self.Partner.pnm_create_vendor('', '55501', False)['vendor']
        self.assertEqual(code_only['label'], '55501')
        self.assertEqual(self.Partner.browse(code_only['id']).name, '55501')

    def test_label_only_inside_part_number_module(self):
        self.assertEqual(self.both.display_name, 'Cong Ty ABC')

    def test_search_by_name_or_code(self):
        by_code = self.Partner.pnm_search_vendors('1029344')
        by_name = self.Partner.pnm_search_vendors('cong ty abc')
        self.assertIn({'id': self.both.id, 'label': '10293442 - Cong Ty ABC'}, by_code)
        self.assertIn(self.both.id, [o['id'] for o in by_name])

    def test_exact_match(self):
        for text in ('10293442', 'cong ty abc', '10293442 - Cong Ty ABC'):
            self.assertEqual(self.Partner.pnm_match_vendor(text)['id'], self.both.id, text)
        self.assertFalse(self.Partner.pnm_match_vendor('1029'))

    def test_create_vendor_rules(self):
        self.assertEqual(self.Partner.pnm_create_vendor('', '', False)['status'], 'missing')
        duplicate = self.Partner.pnm_create_vendor('Other Co', '10293442', False)
        self.assertEqual((duplicate['status'], duplicate['vendor']['id']), ('duplicate_code', self.both.id))
        same_name = self.Partner.pnm_create_vendor('Name Only Co', '', False)
        self.assertEqual(same_name['status'], 'same_name')
        forced = self.Partner.pnm_create_vendor('Name Only Co', '', True)
        self.assertEqual(forced['status'], 'created')
        created = self.Partner.pnm_create_vendor('New Vendor', '777', False)
        self.assertEqual(created['vendor']['label'], '777 - New Vendor')
