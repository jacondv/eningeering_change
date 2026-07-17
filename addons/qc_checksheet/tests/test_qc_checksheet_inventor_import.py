import base64
import json

from odoo.tests.common import HttpCase, TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestQcChecksheetInventorImport(TransactionCase):

    def _create_checksheet(self, machine_model='TEST_MODEL'):
        return self.env['qc.checksheet'].create({
            'name': 'Panel Check Sheet', 'checksheet_type': 'panel_sticker',
            'machine_model': machine_model,
        })

    def _create_bom(self, model='TEST_MODEL'):
        bom = self.env['inventor.bom'].create({'model': model, 'bom_type': 'panel_sticker'})
        self.env['qc.checksheet.inventor.bom.line'].create([
            {'bom_id': bom.id, 'item': 1, 'part_number': 'PN-001', 'description': 'Bracket', 'qty': 2},
            {'bom_id': bom.id, 'item': 2, 'part_number': 'PN-002', 'description': 'Sticker', 'qty': 1},
        ])
        return bom

    def test_wizard_defaults_to_matching_bom(self):
        checksheet = self._create_checksheet()
        bom = self._create_bom()
        wizard = self.env['qc.checksheet.inventor.import.wizard'].with_context(
            default_checksheet_id=checksheet.id).create({})
        self.assertEqual(wizard.bom_id, bom)

    def test_onchange_populates_lines(self):
        checksheet = self._create_checksheet()
        bom = self._create_bom()
        wizard = self.env['qc.checksheet.inventor.import.wizard'].create({
            'checksheet_id': checksheet.id, 'bom_id': bom.id,
        })
        wizard._onchange_bom_id()
        self.assertEqual(len(wizard.line_ids), 2)
        self.assertTrue(all(wizard.line_ids.mapped('selected')))

    def test_import_creates_panel_lines_for_selected_only(self):
        checksheet = self._create_checksheet()
        bom = self._create_bom()
        wizard = self.env['qc.checksheet.inventor.import.wizard'].create({
            'checksheet_id': checksheet.id, 'bom_id': bom.id,
        })
        wizard._onchange_bom_id()
        wizard.line_ids[1].selected = False
        wizard.action_import()

        self.assertEqual(len(checksheet.panel_line_ids), 1)
        imported = checksheet.panel_line_ids[0]
        self.assertEqual(imported.item_number, 1)
        self.assertEqual(imported.part_number, 'PN-001')
        self.assertEqual(imported.description, 'Bracket')
        self.assertEqual(imported.qty, 2)

    def test_import_is_a_snapshot_not_a_live_link(self):
        checksheet = self._create_checksheet()
        bom = self._create_bom()
        wizard = self.env['qc.checksheet.inventor.import.wizard'].create({
            'checksheet_id': checksheet.id, 'bom_id': bom.id,
        })
        wizard._onchange_bom_id()
        wizard.action_import()

        bom_line = self.env['qc.checksheet.inventor.bom.line'].search([
            ('bom_id', '=', bom.id), ('item', '=', 1)])
        bom_line.description = 'Changed after import'

        imported = checksheet.panel_line_ids.filtered(lambda l: l.item_number == 1)
        self.assertEqual(imported.description, 'Bracket')

    def test_bom_id_domain_does_not_require_model_match(self):
        domain = self.env['qc.checksheet.inventor.import.wizard']._fields['bom_id'].domain
        self.assertEqual(domain, [('bom_type', '=', 'panel_sticker')])

    def test_editing_a_wizard_line_before_import_does_not_touch_source_bom_line(self):
        checksheet = self._create_checksheet()
        bom = self._create_bom()
        wizard = self.env['qc.checksheet.inventor.import.wizard'].create({
            'checksheet_id': checksheet.id, 'bom_id': bom.id,
        })
        wizard._onchange_bom_id()
        edited_line = wizard.line_ids[0]
        edited_line.part_number = 'PN-001-CORRECTED'
        wizard.action_import()

        imported = checksheet.panel_line_ids.filtered(lambda l: l.item_number == 1)
        self.assertEqual(imported.part_number, 'PN-001-CORRECTED')

        source_bom_line = self.env['qc.checksheet.inventor.bom.line'].search([
            ('bom_id', '=', bom.id), ('item', '=', 1)])
        self.assertEqual(source_bom_line.part_number, 'PN-001')

    def test_manually_created_panel_line_has_no_item_number(self):
        checksheet = self._create_checksheet()
        line = self.env['qc.checksheet.panel.line'].create({
            'checksheet_id': checksheet.id, 'part_number': 'PN-999',
        })
        self.assertFalse(line.item_number)

    def test_panel_sticker_line_ids_extension_field_writes_through(self):
        bom = self.env['inventor.bom'].create({'model': 'TEST_MODEL', 'bom_type': 'panel_sticker'})
        bom.write({
            'panel_sticker_line_ids': [
                (0, 0, {'item': 1, 'part_number': 'PN-MANUAL', 'description': 'Added by hand', 'qty': 1}),
            ],
        })
        lines = self.env['qc.checksheet.inventor.bom.line'].search([('bom_id', '=', bom.id)])
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines.part_number, 'PN-MANUAL')

    def test_second_sync_replaces_header_and_lines_not_duplicates(self):
        bom = self.env['inventor.bom']._upsert_from_payload({
            'model': 'TEST_MODEL', 'bom_type': 'panel_sticker', 'name': 'First sync',
            'lines': [{'item': 1, 'part_number': 'PN-001'}],
        })
        first_synced = bom.last_synced

        bom2 = self.env['inventor.bom']._upsert_from_payload({
            'model': 'TEST_MODEL', 'bom_type': 'panel_sticker', 'name': 'Second sync',
            'lines': [{'item': 1, 'part_number': 'PN-002'}, {'item': 2, 'part_number': 'PN-003'}],
        })

        self.assertEqual(bom2.id, bom.id)
        self.assertEqual(bom2.name, 'Second sync')
        self.assertGreaterEqual(bom2.last_synced, first_synced)

        lines = self.env['qc.checksheet.inventor.bom.line'].search([('bom_id', '=', bom.id)])
        self.assertEqual(len(lines), 2)
        self.assertEqual(set(lines.mapped('part_number')), {'PN-002', 'PN-003'})


@tagged('post_install', '-at_install')
class TestQcChecksheetInventorImportEndToEnd(HttpCase):
    """Exercises the real inventor_connector REST endpoint end-to-end,
    confirming the panel_sticker bom_type registration (data/
    inventor_bom_type_data.xml) actually routes lines into
    qc.checksheet.inventor.bom.line."""

    def test_post_bom_creates_registered_line_model_records(self):
        self.env['ir.config_parameter'].sudo().set_param('inventor_connector.api_key', 'test-key')
        image = base64.b64encode(b'<svg xmlns="http://www.w3.org/2000/svg"/>').decode()
        payload = {
            'model': 'TEST_MODEL',
            'bom_type': 'panel_sticker',
            'name': 'From Inventor',
            'lines': [
                {'item': 1, 'part_number': 'PN-001', 'description': 'Bracket', 'qty': 2, 'image': image},
            ],
        }
        response = self.url_open(
            '/api/inventor/bom', data=json.dumps(payload),
            headers={'Content-Type': 'application/json', 'X-API-Key': 'test-key'})
        self.assertEqual(response.status_code, 200)

        bom = self.env['inventor.bom'].search([('model', '=', 'TEST_MODEL'), ('bom_type', '=', 'panel_sticker')])
        self.assertEqual(len(bom), 1)
        lines = self.env['qc.checksheet.inventor.bom.line'].search([('bom_id', '=', bom.id)])
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines.part_number, 'PN-001')
        self.assertTrue(lines.image)
