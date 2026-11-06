from odoo.exceptions import UserError
from odoo.tests.common import tagged

from .common import QcChecksheetCase


@tagged('post_install', '-at_install')
class TestQcChecksheet(QcChecksheetCase):

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

    def test_show_in_report_defaults_true(self):
        checksheet = self._create_checksheet()
        self.assertTrue(checksheet.history_ids.show_in_report)

    def test_report_omits_history_lines_hidden_from_report(self):
        checksheet = self._create_checksheet()
        self.env['qc.checksheet.history'].create({
            'checksheet_id': checksheet.id, 'rev': 1, 'description': 'Shown', 'show_in_report': True})
        self.env['qc.checksheet.history'].create({
            'checksheet_id': checksheet.id, 'rev': 2, 'description': 'Hidden', 'show_in_report': False})

        report = self.env.ref('qc_checksheet.action_report_qc_checksheet')
        html = report.sudo()._render_qweb_html(report.report_name, checksheet.ids)[0].decode()
        self.assertIn('Shown', html)
        self.assertNotIn('Hidden', html)

    def test_copy_content_from_standard(self):
        source_job = self._create_job('J-SOURCE', machine_serial='SN-OLD')
        source = self._create_checksheet(job=source_job, check_date='2026-01-15')
        source.write({'approval_ids': [(0, 0, {'sequence': 10, 'position': 'Technician'})]})
        self._create_content(source)
        self._release(source)

        target_job = self._create_job('J-TARGET', machine_serial='SN-NEW')
        copy = self._create_checksheet(job=target_job)
        copy._copy_content_from(source)

        self.assertEqual(copy.copied_from_id, source)
        self.assertIn('Hydraulic System', copy.group_ids.name)
        self.assertIn('Check oil level', copy.group_ids.item_ids.description)
        self.assertEqual(copy.approval_ids.mapped('position'), ['Technician'])
        # Independent copy: editing the copy must not affect the source.
        copy.group_ids.name = 'Renamed'
        self.assertIn('Hydraulic System', source.group_ids.name)

        # Starts over at Rev 0, keeping nothing specific to the old machine.
        self.assertEqual(copy.revision, 0)
        self.assertEqual(copy.state, 'draft')
        self.assertEqual(copy.machine_serial, 'SN-NEW')
        self.assertFalse(copy.check_date)
        self.assertEqual(copy.history_ids.mapped('rev'), [0])
        self.assertIn('J-SOURCE', copy.history_ids.description)

    def test_copy_content_requires_released_source(self):
        source = self._create_checksheet()
        self._create_content(source)
        with self.assertRaises(UserError):
            self._create_checksheet()._copy_content_from(source)

    def test_copy_content_refuses_target_with_content(self):
        source = self._release(self._create_checksheet())
        self._create_content(source)
        target = self._create_checksheet()
        self._create_content(target)
        with self.assertRaises(UserError):
            target._copy_content_from(source)

    def test_copy_content_type_mismatch_raises(self):
        source = self._release(self._create_checksheet())
        panel_copy = self._create_checksheet(self.type_panel)
        with self.assertRaises(UserError):
            panel_copy._copy_content_from(source)

    def test_copy_wizard_copies_content_into_existing_checksheet(self):
        source = self._create_checksheet()
        self._create_content(source, 'Question 1')
        self._release(source)

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
        other_standard = self._release(self._create_checksheet())
        panel_source = self._release(self._create_checksheet(self.type_panel))
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
