from odoo.exceptions import UserError
from odoo.tests.common import new_test_user, tagged

from .common import QcChecksheetCase


@tagged('post_install', '-at_install')
class TestQcChecksheetEngineeringChange(QcChecksheetCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.author = new_test_user(
            cls.env, login='qc_ec_author', groups='base.group_user,qc_checksheet.group_qc_author')

    def _change(self, name, state='implement', job=None, model=None):
        change = self.env['engineering.change'].create({
            'title': f'Title of {name}',
            'description': '<p>Description</p>',
            'request_type': 'minor',
            'rpn': 50,
            'change_category': 'standard',
            'engineer_id': self.author.id,
            'impact_negative': 'no',
            'impact_cost_over_100': 'no',
            'impact_lead_time_over_week': 'no',
            'impact_circuit_change': 'no',
        })
        change.with_context(ec_workflow_write=True).write({'state': state})
        change.name = name
        if job or model:
            self.env['project.task'].create({
                'change_id': change.id, 'name': 'Do it',
                'affected_project_ids': [(6, 0, job.ids if job else [])],
                'affected_model_ids': [(6, 0, model.ids if model else [])],
            })
        return change

    def _released(self, model=None):
        sheet = self._create_checksheet(model=model)
        self._create_content(sheet)
        sheet.action_submit()
        sheet.action_approve()
        return sheet

    def test_new_revision_records_its_changes(self):
        rev0 = self._released()
        change = self._change('EC-T1')
        rev1 = rev0.browse(rev0.action_create_revision('Raise limit', [change.id])['res_id'])
        self.assertEqual(rev1.change_request_ids, change)
        self.assertFalse(rev0.change_request_ids)

    def test_a_revision_without_changes_is_fine(self):
        rev0 = self._released()
        rev1 = rev0.browse(rev0.action_create_revision('Fix a typo')['res_id'])
        self.assertFalse(rev1.change_request_ids)

    def test_the_wizard_passes_the_changes(self):
        rev0 = self._released()
        change = self._change('EC-T2')
        wizard = self.env['qc.checksheet.new.revision.wizard'].create({
            'checksheet_id': rev0.id, 'reason': 'Because', 'change_ids': [(6, 0, [change.id])]})
        rev1 = rev0.browse(wizard.action_create()['res_id'])
        self.assertEqual(rev1.change_request_ids, change)

    def test_changes_can_be_set_in_draft_only(self):
        sheet = self._create_checksheet().with_user(self.author)
        self._create_content(sheet)
        first, second = self._change('EC-T3'), self._change('EC-T4')
        result = sheet.editor_set_changes([first.id, second.id])
        self.assertEqual([c['name'] for c in result], ['EC-T3', 'EC-T4'])
        self.assertEqual(sheet.change_request_ids, first | second)
        sheet.editor_set_changes([second.id])
        self.assertEqual(sheet.change_request_ids, second)
        sheet.action_submit()
        with self.assertRaises(UserError):
            sheet.editor_set_changes([first.id])
        with self.assertRaisesRegex(UserError, 'locked'):
            sheet.write({'change_request_ids': [(6, 0, [first.id])]})

    def test_editor_load_lists_the_changes(self):
        sheet = self._create_checksheet()
        change = self._change('EC-T5')
        sheet.change_request_ids = change
        self.assertEqual(sheet.editor_load()['changes'], [
            {'id': change.id, 'name': 'EC-T5', 'title': 'Title of EC-T5', 'state_label': 'Design'}])

    def test_search_lists_changes_on_the_model_first_and_skips_unusable_ones(self):
        model = self._create_model()
        sheet = self._create_checksheet(model=model)
        elsewhere = self._change('EC-T6')
        on_model = self._change('EC-T7', model=model)
        self._change('EC-T8', state='draft')
        self._change('EC-T9', state='canceled')
        found = sheet.editor_search_changes('EC-T')
        self.assertEqual([c['name'] for c in found], ['EC-T7', 'EC-T6'])
        self.assertEqual([c['affects'] for c in found], [True, False])
        self.assertEqual([c['id'] for c in sheet.editor_search_changes('Title of EC-T6')], [elsewhere.id])
        self.assertEqual(found[0]['id'], on_model.id)

    def test_pdf_prints_the_changes_with_their_revision(self):
        rev0 = self._released()
        change = self._change('EC-T10')
        rev1 = rev0.browse(rev0.action_create_revision('Raise limit', [change.id])['res_id'])
        html = self.env['ir.actions.report']._render_qweb_html(
            'qc_checksheet.report_qc_checksheet_document', rev1.ids)[0].decode()
        self.assertIn('Raise limit', html)
        self.assertIn('EC-T10', html)
        # Rev 0 has none, and prints nothing of the sort.
        html = self.env['ir.actions.report']._render_qweb_html(
            'qc_checksheet.report_qc_checksheet_document', rev0.ids)[0].decode()
        self.assertNotIn('EC-T10', html)

    def test_the_change_lists_its_sheets(self):
        change = self._change('EC-T11')
        sheet = self._create_checksheet()
        sheet.change_request_ids = change
        self.assertEqual(change.qc_checksheet_count, 1)
        action = change.action_view_qc_checksheets()
        self.assertEqual(self.env['qc.checksheet'].search(action['domain']), sheet)

    def test_job_page_flags_the_changes_in_progress(self):
        job = self._create_job()
        running = self._change('EC-T12', job=job)
        self._change('EC-T13', state='done', job=job)
        self._change('EC-T14', state='draft', job=job)
        self._change('EC-T15')
        overview = self.env['qc.job.checksheet'].job_overview(job.id)
        self.assertEqual([c['id'] for c in overview['changes']], [running.id])

    def test_model_page_flags_the_changes_in_progress(self):
        model = self._create_model()
        running = self._change('EC-T16', model=model)
        self._change('EC-T17', state='done', model=model)
        self._change('EC-T18')
        overview = self.env['qc.checksheet'].model_overview(model.id)
        self.assertEqual([c['id'] for c in overview['changes']], [running.id])
