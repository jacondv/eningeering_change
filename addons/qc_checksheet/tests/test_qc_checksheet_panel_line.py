from odoo.tests.common import TransactionCase, tagged


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
            })],
        })
        self.assertEqual(group.image_line_ids.description, 'Front view')
        self.assertEqual(group.image_line_ids.size_percent, 50)
        self.assertEqual(group.image_line_ids.width_percent, 60)

    def test_copy_content_from_copies_image_groups(self):
        source = self._create_checksheet()
        self.env['qc.checksheet.image.group'].create({
            'checksheet_id': source.id,
            'name': 'Overview',
            'image_line_ids': [(0, 0, {
                'description': 'Front view', 'size_percent': 50, 'width_percent': 60,
            })],
        })

        copy = self._create_checksheet()
        copy._copy_content_from(source)

        self.assertEqual(copy.image_group_ids.name, 'Overview')
        self.assertEqual(copy.image_group_ids.image_line_ids.description, 'Front view')
        self.assertEqual(copy.image_group_ids.image_line_ids.size_percent, 50)
        self.assertEqual(copy.image_group_ids.image_line_ids.width_percent, 60)
