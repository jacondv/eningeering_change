from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestQcChecksheet(TransactionCase):

    def _create_checksheet(self):
        return self.env['qc.checksheet'].create({
            'name': 'Start Up Check Sheet',
            'checksheet_type': 'standard',
        })

    def test_item_number_is_continuous_across_groups(self):
        checksheet = self._create_checksheet()
        group_a = self.env['qc.checksheet.group'].create({
            'checksheet_id': checksheet.id, 'sequence': 10, 'name': 'Group A',
            'item_ids': [(0, 0, {'sequence': s}) for s in (10, 20, 30)],
        })
        group_b = self.env['qc.checksheet.group'].create({
            'checksheet_id': checksheet.id, 'sequence': 20, 'name': 'Group B',
            'item_ids': [(0, 0, {'sequence': s}) for s in (10, 20)],
        })
        self.assertEqual(group_a.item_ids.mapped('item_number'), [1, 2, 3])
        self.assertEqual(group_b.item_ids.mapped('item_number'), [4, 5])

    def test_item_number_renumbers_on_new_item_in_earlier_group(self):
        checksheet = self._create_checksheet()
        group_a = self.env['qc.checksheet.group'].create({
            'checksheet_id': checksheet.id, 'sequence': 10, 'name': 'Group A',
            'item_ids': [(0, 0, {'sequence': 10})],
        })
        group_b = self.env['qc.checksheet.group'].create({
            'checksheet_id': checksheet.id, 'sequence': 20, 'name': 'Group B',
            'item_ids': [(0, 0, {'sequence': 10})],
        })
        self.assertEqual(group_b.item_ids.item_number, 2)

        self.env['qc.checksheet.item'].create({'group_id': group_a.id, 'sequence': 20})
        self.assertEqual(group_b.item_ids.item_number, 3)

    def test_copy_content_from_standard(self):
        source = self._create_checksheet()
        source.write({
            'machine_serial': 'SN-123', 'customer': 'ACME Co',
            'approval_ids': [(0, 0, {'sequence': 10, 'position': 'Technician'})],
            'history_ids': [(0, 0, {'sequence': 10, 'rev': '1', 'description': 'Initial'})],
        })
        self.env['qc.checksheet.group'].create({
            'checksheet_id': source.id, 'name': 'Hydraulic System',
            'item_ids': [(0, 0, {'description': 'Check oil level', 'acceptance': 'No leak'})],
        })

        copy = self._create_checksheet()
        copy._copy_content_from(source)

        self.assertEqual(copy.copied_from_id, source)
        self.assertIn('Hydraulic System', copy.group_ids.name)
        self.assertIn('Check oil level', copy.group_ids.item_ids.description)
        self.assertEqual(copy.machine_serial, 'SN-123')
        self.assertEqual(copy.customer, 'ACME Co')
        self.assertEqual(copy.approval_ids.mapped('position'), ['Technician'])
        self.assertEqual(copy.history_ids.mapped('rev'), ['1'])
        # Independent copy: editing the copy must not affect the source.
        copy.group_ids.name = 'Renamed'
        self.assertIn('Hydraulic System', source.group_ids.name)

    def test_copy_content_type_mismatch_raises(self):
        source = self._create_checksheet()
        panel_copy = self.env['qc.checksheet'].create({
            'name': 'Panel Copy', 'checksheet_type': 'panel_sticker',
        })
        with self.assertRaises(UserError):
            panel_copy._copy_content_from(source)

    def test_copy_wizard_copies_content_into_existing_checksheet(self):
        source = self._create_checksheet()
        self.env['qc.checksheet.group'].create({
            'checksheet_id': source.id, 'name': 'Group A',
            'item_ids': [(0, 0, {'description': 'Question 1'})],
        })

        new_checksheet = self._create_checksheet()
        wizard = self.env['qc.checksheet.copy.wizard'].create({
            'checksheet_id': new_checksheet.id,
            'source_checksheet_id': source.id,
        })
        wizard.action_copy()

        self.assertEqual(new_checksheet.copied_from_id, source)
        self.assertIn('Question 1', new_checksheet.group_ids.item_ids.description)

    def test_copy_wizard_rejects_type_mismatch(self):
        checksheet = self._create_checksheet()
        other_standard = self._create_checksheet()
        panel_source = self.env['qc.checksheet'].create({
            'name': 'Panel Source', 'checksheet_type': 'panel_sticker',
        })
        wizard = self.env['qc.checksheet.copy.wizard'].create({
            'checksheet_id': checksheet.id,
            'source_checksheet_id': other_standard.id,
        })
        # Force a mismatched source past the view's domain (the domain is a
        # UI hint only) to prove the server-side guard in _copy_content_from
        # actually rejects it too.
        wizard.source_checksheet_id = panel_source
        with self.assertRaises(UserError):
            wizard.action_copy()
