import base64

from odoo.tests.common import TransactionCase, tagged

SVG_WITH_LEGACY_FONT = b'''<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100">
<defs><style>
@font-face { font-family:"Arial";font-variant:normal;font-weight:bold;src:url("#FontID1") format(svg)}
</style>
<font id="FontID1" horiz-adv-x="1000"><font-face font-family="Arial"/><glyph unicode="E" d="M0 0"/></font>
</defs>
<text x="10" y="50" font-family="Arial">EMERGENCY</text>
</svg>'''

PNG_1X1 = base64.b64decode(
    b'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=')


@tagged('post_install', '-at_install')
class TestQcChecksheetPanelLine(TransactionCase):

    def _create_checksheet(self):
        return self.env['qc.checksheet'].create({
            'name': 'Panel Check Sheet', 'checksheet_type': 'panel_sticker',
        })

    def test_create_panel_line_manually(self):
        checksheet = self._create_checksheet()
        line = self.env['qc.checksheet.panel.line'].create({
            'checksheet_id': checksheet.id,
            'part_number': 'PN-001',
            'description': 'Bracket',
            'qty': 2,
            'note': 'Handle with care',
        })
        self.assertEqual(line.part_number, 'PN-001')
        self.assertEqual(line.description, 'Bracket')
        self.assertEqual(line.qty, 2)

    def test_copy_content_from_copies_panel_lines(self):
        source = self._create_checksheet()
        self.env['qc.checksheet.panel.line'].create({
            'checksheet_id': source.id,
            'part_number': 'PN-001', 'description': 'Bracket', 'qty': 2,
        })

        copy = self._create_checksheet()
        copy._copy_content_from(source)

        self.assertEqual(copy.copied_from_id, source)
        self.assertEqual(copy.panel_line_ids.part_number, 'PN-001')
        self.assertEqual(copy.panel_line_ids.qty, 2)

    def test_create_image_group_manually(self):
        checksheet = self._create_checksheet()
        group = self.env['qc.checksheet.image.group'].create({
            'checksheet_id': checksheet.id,
            'name': 'Overview',
            'image_line_ids': [(0, 0, {
                'description': 'Front view', 'size_percent': 50, 'width_percent': 60,
                'page_break_after': True, 'keep_original_size': True,
            })],
        })
        self.assertEqual(group.image_line_ids.description, 'Front view')
        self.assertEqual(group.image_line_ids.size_percent, 50)
        self.assertEqual(group.image_line_ids.width_percent, 60)
        self.assertTrue(group.image_line_ids.page_break_after)
        self.assertTrue(group.image_line_ids.keep_original_size)

    def test_copy_content_from_copies_image_groups(self):
        source = self._create_checksheet()
        self.env['qc.checksheet.image.group'].create({
            'checksheet_id': source.id,
            'name': 'Overview',
            'image_line_ids': [(0, 0, {
                'description': 'Front view', 'size_percent': 50, 'width_percent': 60,
                'page_break_after': True, 'keep_original_size': True,
            })],
        })

        copy = self._create_checksheet()
        copy._copy_content_from(source)

        self.assertEqual(copy.image_group_ids.name, 'Overview')
        self.assertEqual(copy.image_group_ids.image_line_ids.description, 'Front view')
        self.assertEqual(copy.image_group_ids.image_line_ids.size_percent, 50)
        self.assertEqual(copy.image_group_ids.image_line_ids.width_percent, 60)
        self.assertTrue(copy.image_group_ids.image_line_ids.page_break_after)
        self.assertTrue(copy.image_group_ids.image_line_ids.keep_original_size)

    def test_pdf_safe_image_strips_legacy_svg_font(self):
        checksheet = self._create_checksheet()
        line = self.env['qc.checksheet.panel.line'].create({
            'checksheet_id': checksheet.id,
            'image': base64.b64encode(SVG_WITH_LEGACY_FONT),
        })
        uri = line._pdf_safe_image_data_uri()
        self.assertTrue(uri.startswith('data:image/svg+xml;base64,'))
        stripped_svg = base64.b64decode(uri.split(',', 1)[1])
        self.assertNotIn(b'format(svg)', stripped_svg)
        self.assertNotIn(b'<font', stripped_svg)
        self.assertIn(b'EMERGENCY', stripped_svg)

    def test_pdf_safe_image_leaves_raster_image_untouched(self):
        checksheet = self._create_checksheet()
        line = self.env['qc.checksheet.panel.line'].create({
            'checksheet_id': checksheet.id,
            'image': base64.b64encode(PNG_1X1),
        })
        uri = line._pdf_safe_image_data_uri()
        self.assertTrue(uri.startswith('data:image/png;base64,'))
        self.assertEqual(base64.b64decode(uri.split(',', 1)[1]), line.image and base64.b64decode(line.image))

    def test_pdf_safe_image_empty_when_no_image(self):
        checksheet = self._create_checksheet()
        line = self.env['qc.checksheet.panel.line'].create({'checksheet_id': checksheet.id})
        self.assertEqual(line._pdf_safe_image_data_uri(), '')
