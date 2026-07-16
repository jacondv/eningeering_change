import base64
import json

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

from ..wizard.qc_checksheet_import_wizard import CONFIG_PARAM_KEY


@tagged('post_install', '-at_install')
class TestQcChecksheetPanelLine(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.checksheet = cls.env['qc.checksheet'].create({
            'name': 'Panel Check Sheet', 'checksheet_type': 'panel_sticker',
        })
        cls.product = cls.env['product.product'].create({'name': 'Bracket', 'default_code': 'PN-001'})

    def test_onchange_part_number_fills_description(self):
        line = self.env['qc.checksheet.panel.line'].new({
            'checksheet_id': self.checksheet.id, 'part_number': self.product.id,
        })
        line._onchange_part_number()
        self.assertEqual(line.description, 'Bracket')

    def test_product_found_computed(self):
        line = self.env['qc.checksheet.panel.line'].create({
            'checksheet_id': self.checksheet.id, 'part_number': self.product.id,
        })
        self.assertTrue(line.product_found)

        empty_line = self.env['qc.checksheet.panel.line'].create({'checksheet_id': self.checksheet.id})
        self.assertFalse(empty_line.product_found)

    def test_action_update_from_product_refreshes_description(self):
        line = self.env['qc.checksheet.panel.line'].create({
            'checksheet_id': self.checksheet.id, 'part_number': self.product.id, 'description': 'Stale',
        })
        self.product.name = 'Bracket Rev B'
        line.action_update_from_product()
        self.assertEqual(line.description, 'Bracket Rev B')

    def test_copy_content_from_copies_panel_lines(self):
        self.env['qc.checksheet.panel.line'].create({
            'checksheet_id': self.checksheet.id, 'part_number': self.product.id,
            'description': 'Bracket', 'qty': 2,
        })
        copy = self.env['qc.checksheet'].create({
            'name': 'Panel Copy', 'checksheet_type': 'panel_sticker',
        })
        copy._copy_content_from(self.checksheet)

        self.assertEqual(copy.copied_from_id, self.checksheet)
        self.assertEqual(copy.panel_line_ids.part_number, self.product)
        self.assertEqual(copy.panel_line_ids.qty, 2)


@tagged('post_install', '-at_install')
class TestQcChecksheetImportWizard(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.checksheet = cls.env['qc.checksheet'].create({
            'name': 'Panel Check Sheet', 'checksheet_type': 'panel_sticker',
        })
        cls.product = cls.env['product.product'].create({'name': 'Bracket', 'default_code': 'PN-001'})

    def _make_wizard(self, csv_text, **extra):
        vals = {
            'checksheet_id': self.checksheet.id,
            'import_file': base64.b64encode(csv_text.encode('utf-8')),
            'import_filename': 'panel_lines.csv',
            'part_number_column': 'part_number',
            'qty_column': 'qty',
            'note_column': 'note',
        }
        vals.update(extra)
        return self.env['qc.checksheet.import.wizard'].create(vals)

    def test_import_matches_known_product(self):
        csv_text = "part_number,qty,note\nPN-001,3,Handle with care\n"
        wizard = self._make_wizard(csv_text)
        wizard.action_import()

        line = self.checksheet.panel_line_ids
        self.assertEqual(len(line), 1)
        self.assertEqual(line.part_number, self.product)
        self.assertEqual(line.description, 'Bracket')
        self.assertEqual(line.qty, 3.0)
        self.assertTrue(line.product_found)

    def test_import_unmatched_product_flagged(self):
        csv_text = "part_number,qty,note\nUNKNOWN-999,1,\n"
        wizard = self._make_wizard(csv_text)
        wizard.action_import()

        line = self.checksheet.panel_line_ids
        self.assertFalse(line.part_number)
        self.assertFalse(line.product_found)
        self.assertIn('UNKNOWN-999', line.description)

    def test_import_append_vs_replace(self):
        csv_text = "part_number,qty,note\nPN-001,1,\n"
        self._make_wizard(csv_text).action_import()
        self.assertEqual(len(self.checksheet.panel_line_ids), 1)

        self._make_wizard(csv_text).action_import()
        self.assertEqual(len(self.checksheet.panel_line_ids), 2, "Default import should append.")

        self._make_wizard(csv_text, replace_existing=True).action_import()
        self.assertEqual(len(self.checksheet.panel_line_ids), 1, "replace_existing should clear old lines first.")

    def test_import_remembers_column_mapping(self):
        csv_text = "code,quantity,remark\nPN-001,2,ok\n"
        wizard = self._make_wizard(
            csv_text, part_number_column='code', qty_column='quantity', note_column='remark')
        wizard.action_import()

        mapping = json.loads(self.env['ir.config_parameter'].sudo().get_param(CONFIG_PARAM_KEY))
        self.assertEqual(mapping['part_number_column'], 'code')

        new_wizard_defaults = self.env['qc.checksheet.import.wizard'].default_get(
            ['part_number_column', 'qty_column', 'note_column'])
        self.assertEqual(new_wizard_defaults['part_number_column'], 'code')

    def test_import_unsupported_extension_raises(self):
        wizard = self._make_wizard("part_number\nPN-001\n", import_filename='panel_lines.txt')
        with self.assertRaises(UserError):
            wizard.action_import()
