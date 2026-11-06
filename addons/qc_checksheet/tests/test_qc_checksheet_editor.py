from odoo.exceptions import AccessError, UserError
from odoo.tests.common import new_test_user, tagged

from .common import QcChecksheetCase


@tagged('post_install', '-at_install')
class TestQcChecksheetEditor(QcChecksheetCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.author = new_test_user(
            cls.env, login='qc_editor_author', groups='base.group_user,qc_checksheet.group_qc_author')
        cls.approver = new_test_user(
            cls.env, login='qc_editor_approver', groups='base.group_user,qc_checksheet.group_qc_approver')
        cls.viewer = new_test_user(cls.env, login='qc_editor_viewer', groups='base.group_user')

    def _sheet(self):
        checksheet = self._create_checksheet().with_user(self.author)
        self._create_content(checksheet)
        return checksheet

    def _payload(self, checksheet, **changes):
        data = checksheet.editor_load()
        data.update(changes)
        return data

    def test_load_returns_the_whole_sheet(self):
        checksheet = self._sheet()
        data = checksheet.editor_load()
        self.assertEqual(data['number'], 'QC-GE-ZA90')
        self.assertEqual(data['revision'], 0)
        self.assertEqual(data['state'], 'draft')
        self.assertIn('Hydraulic System', data['groups'][0]['name'])
        self.assertIn('Check oil level', data['groups'][0]['items'][0]['description'])
        self.assertEqual(data['history'][0]['sheet_id'], checksheet.id)
        self.assertTrue(data['can_author'])
        self.assertFalse(data['can_approve'])

    def test_load_gives_what_comparing_revisions_needs(self):
        rev0 = self._sheet()
        rev0.action_submit()
        rev0.with_user(self.approver).action_approve()
        rev1 = rev0.browse(rev0.action_create_revision('Change')['res_id'])
        data = rev1.editor_load()
        self.assertEqual(
            [(r['id'], r['revision']) for r in data['revisions']], [(rev0.id, 0), (rev1.id, 1)])
        old = rev0.editor_load()
        self.assertEqual(data['groups'][0]['line_key'], old['groups'][0]['line_key'])
        self.assertEqual(data['groups'][0]['items'][0]['line_key'], old['groups'][0]['items'][0]['line_key'])
        self.assertTrue(data['groups'][0]['items'][0]['line_key'])

    def test_viewer_can_load_but_not_save(self):
        checksheet = self._sheet().with_user(self.viewer)
        data = checksheet.editor_load()
        self.assertFalse(data['can_author'])
        with self.assertRaises(AccessError):
            checksheet.editor_save(data)

    def test_save_edits_adds_and_removes_rows(self):
        checksheet = self._sheet()
        payload = self._payload(checksheet, name='New Header')
        group = payload['groups'][0]
        kept = group['items'][0]
        kept['description'] = '<p>Edited</p>'
        kept['note'] = '<p>First line</p><p>Second line</p>'
        group['items'].append({'id': False, 'description': '<p>Added</p>', 'acceptance': '', 'note': ''})
        payload['groups'].append({'id': False, 'name': '<p>Engine</p>', 'items': [
            {'id': False, 'description': '<p>Idle</p>', 'acceptance': '', 'note': ''},
        ]})
        payload['positions'] = [{'id': False, 'position': 'QC Inspector'}]

        saved = checksheet.editor_save(payload)

        self.assertEqual(checksheet.name, 'New Header')
        self.assertEqual(len(checksheet.group_ids), 2)
        self.assertEqual(checksheet.group_ids.item_ids.mapped('item_number'), [1, 2, 3])
        first = checksheet.group_ids[0].item_ids[0]
        self.assertEqual(first.id, kept['id'])
        self.assertIn('Edited', first.description)
        self.assertIn('Second line', first.note)
        self.assertEqual(checksheet.approval_ids.mapped('position'), ['QC Inspector'])
        self.assertEqual(saved['groups'][1]['id'], checksheet.group_ids[1].id)
        self.assertEqual(saved['groups'][1]['item_ids'], checksheet.group_ids[1].item_ids.ids)
        self.assertEqual(saved['positions'], checksheet.approval_ids.ids)

    def test_save_removes_rows_left_out(self):
        checksheet = self._sheet()
        payload = self._payload(checksheet)
        payload['groups'][0]['items'] = []
        checksheet.editor_save(payload)
        self.assertFalse(checksheet.group_ids.item_ids)

        payload = self._payload(checksheet)
        payload['groups'] = []
        checksheet.editor_save(payload)
        self.assertFalse(checksheet.group_ids)

    def test_save_moves_an_item_out_of_a_deleted_group(self):
        checksheet = self._sheet()
        self._create_content(checksheet, 'Second group item')
        first_group, second_group = checksheet.group_ids
        moved = first_group.item_ids
        payload = self._payload(checksheet)
        payload['groups'][1]['items'].insert(0, payload['groups'][0]['items'][0])
        del payload['groups'][0]

        checksheet.editor_save(payload)

        self.assertFalse(first_group.exists())
        self.assertTrue(moved.exists())
        self.assertEqual(moved.group_id, second_group)
        self.assertEqual(second_group.item_ids[0], moved)

    def test_save_keeps_line_keys(self):
        checksheet = self._sheet()
        key = checksheet.group_ids.item_ids.line_key
        payload = self._payload(checksheet)
        payload['groups'][0]['items'][0]['description'] = '<p>Edited</p>'
        checksheet.editor_save(payload)
        self.assertEqual(checksheet.group_ids.item_ids.line_key, key)

    def test_save_refuses_a_stale_page(self):
        checksheet = self._sheet()
        stale = self._payload(checksheet)
        checksheet.editor_save(self._payload(checksheet, name='Saved First'))
        with self.assertRaises(UserError):
            checksheet.editor_save(stale)
        self.assertEqual(checksheet.name, 'Saved First')

    def test_save_refuses_rows_of_another_sheet(self):
        checksheet = self._sheet()
        other = self._sheet()
        payload = self._payload(checksheet)
        payload['groups'][0]['id'] = other.group_ids.id
        with self.assertRaises(UserError):
            checksheet.editor_save(payload)
        self.assertTrue(other.group_ids.exists())

    def test_save_is_refused_once_submitted(self):
        checksheet = self._sheet()
        payload = self._payload(checksheet)
        checksheet.action_submit()
        with self.assertRaises(UserError):
            checksheet.editor_save(payload)

    def test_save_needs_a_header_and_named_positions(self):
        checksheet = self._sheet()
        with self.assertRaises(UserError):
            checksheet.editor_save(self._payload(checksheet, name='  '))
        with self.assertRaises(UserError):
            checksheet.editor_save(self._payload(checksheet, positions=[{'id': False, 'position': ' '}]))

    def test_save_changes_only_the_current_history_row(self):
        rev0 = self._sheet()
        rev0.action_submit()
        rev0.with_user(self.approver).action_approve()
        rev1 = rev0.browse(rev0.action_create_revision('First reason')['res_id'])
        payload = self._payload(rev1)
        payload['history'][0]['description'] = 'Tampered'
        payload['history'][1].update({'description': 'Reworded', 'date': '2026-01-15', 'show_in_report': False})

        rev1.editor_save(payload)

        old_line, current_line = rev1.history_ids
        self.assertEqual(old_line.description, 'Initial issue')
        self.assertEqual(current_line.description, 'Reworded')
        self.assertEqual(str(current_line.date), '2026-01-15')
        self.assertFalse(current_line.show_in_report)

    def test_submit_refuses_blank_rows(self):
        checksheet = self._sheet()
        payload = self._payload(checksheet)
        payload['groups'][0]['items'].append({'id': False, 'description': '<p><br></p>', 'acceptance': '', 'note': ''})
        checksheet.editor_save(payload)
        with self.assertRaisesRegex(UserError, 'Item 2'):
            checksheet.action_submit()

    def test_submit_refuses_an_unnamed_group(self):
        checksheet = self._sheet()
        checksheet.group_ids.write({'name': '<p><br></p>'})
        with self.assertRaises(UserError):
            checksheet.action_submit()

    def test_item_with_only_an_image_is_not_blank(self):
        checksheet = self._sheet()
        checksheet.group_ids.item_ids.write({'description': '<p><img src="/web/image/1-abc/x.png"></p>'})
        checksheet.action_submit()
        self.assertEqual(checksheet.state, 'review')

    def test_report_prints_a_rich_note(self):
        checksheet = self._sheet()
        checksheet.group_ids.item_ids.write({'note': '<p>First line</p><p>Second line</p>'})
        report = self.env.ref('qc_checksheet.action_report_qc_checksheet')
        html = report.sudo()._render_qweb_html(report.report_name, checksheet.ids)[0].decode()
        self.assertIn('<p>Second line</p>', html)
        self.assertNotIn('&lt;p&gt;', html)

    def _image_attachment(self, res_model, res_id=0):
        return self.env['ir.attachment'].sudo().create({
            'name': 'pasted.png', 'res_model': res_model, 'res_id': res_id,
            'raw': b'\x89PNG\r\n\x1a\n pasted image', 'mimetype': 'image/png',
        })

    def test_pasted_image_is_claimed_on_save(self):
        checksheet = self._sheet()
        attachment = self._image_attachment('qc.checksheet.item')
        payload = self._payload(checksheet)
        new_note = f'<p><img src="/web/image/{attachment.id}-{attachment.checksum[:8]}/pasted.png"></p>'
        payload['groups'][0]['items'][0]['note'] = new_note
        checksheet.editor_save(payload)
        item = checksheet.group_ids.item_ids
        self.assertEqual(attachment.res_id, item.id)
        self.assertEqual(attachment.res_model, 'qc.checksheet.item')

    def test_new_revision_gets_its_own_copy_of_an_image(self):
        checksheet = self._sheet()
        item = checksheet.group_ids.item_ids
        attachment = self._image_attachment('qc.checksheet.item', item.id)
        src = f'/web/image/{attachment.id}-{attachment.checksum[:8]}/pasted.png'
        item.write({'description': f'<p>See <img src="{src}"></p>'})
        checksheet.action_submit()
        checksheet.with_user(self.approver).action_approve()

        rev1 = checksheet.browse(checksheet.action_create_revision('Change')['res_id'])

        new_item = rev1.group_ids.item_ids
        self.assertIn(src, item.description)
        self.assertNotIn(f'/web/image/{attachment.id}-', new_item.description)
        copies = self.env['ir.attachment'].sudo().search([
            ('res_model', '=', 'qc.checksheet.item'), ('res_id', '=', new_item.id)])
        self.assertEqual(copies.checksum, attachment.checksum)

    # New Check Sheet page

    def test_jobs_offered_are_those_with_a_model(self):
        job = self._create_job('J-EDITOR-1')
        self.env['project.project'].create({'name': 'J-EDITOR-NO-MODEL'})
        results = self.env['qc.checksheet'].with_user(self.author).editor_search_jobs('J-EDITOR')
        self.assertEqual([result['id'] for result in results], [job.id])
        self.assertEqual(results[0]['model'], 'ZA90')

    def test_new_context_previews_the_sheet(self):
        category = self.env['equipment.model.category'].create({'name': 'Category'})
        self.model_za90.family_id = self.env['equipment.model.family'].create({
            'name': 'Family', 'description': 'Zero\nLoader', 'category_id': category.id,
        })
        job = self._create_job(machine_serial='SN-9')
        Sheet = self.env['qc.checksheet'].with_user(self.author)
        context = Sheet.editor_new_context(job.id, self.type_general.id)
        self.assertEqual(context['number'], 'QC-GE-ZA90')
        self.assertEqual(context['header'], 'Zero Loader')
        self.assertEqual(context['serial'], 'SN-9')
        self.assertFalse(context['duplicate_id'])

        existing = self._create_checksheet(job=job)
        context = Sheet.editor_new_context(job.id, self.type_general.id)
        self.assertEqual(context['duplicate_id'], existing.id)

    def test_new_context_lists_released_sources_same_model_first(self):
        other_model = self.env['equipment.model'].create({'name': 'ZB10'})
        other = self._release(self._create_checksheet(job=self._create_job(model=other_model)))
        same = self._release(self._create_checksheet())
        self._create_checksheet()
        self._release(self._create_checksheet(self.type_panel))
        job = self._create_job()
        sources = self.env['qc.checksheet'].with_user(self.author).editor_new_context(
            job.id, self.type_general.id)['sources']
        ids = [source['id'] for source in sources]
        self.assertIn(same.id, ids)
        self.assertIn(other.id, ids)
        self.assertLess(ids.index(same.id), ids.index(other.id))
        self.assertEqual(
            self.env['qc.checksheet'].browse(ids).mapped('state'), ['released'] * len(ids))
        self.assertEqual(
            set(self.env['qc.checksheet'].browse(ids).mapped('checksheet_type')), {'standard'})

    def test_create_blank_starts_with_one_empty_row(self):
        created = self.env['qc.checksheet'].with_user(self.author).editor_create({
            'job_id': self._create_job().id, 'type_id': self.type_general.id, 'header': 'My Header',
        })
        checksheet = self.env['qc.checksheet'].browse(created['id'])
        self.assertEqual(created['layout'], 'standard')
        self.assertEqual(checksheet.name, 'My Header')
        self.assertEqual(checksheet.revision, 0)
        self.assertEqual(len(checksheet.group_ids), 1)
        self.assertEqual(len(checksheet.group_ids.item_ids), 1)

    def test_create_can_copy_from_a_released_sheet(self):
        source = self._create_checksheet()
        self._create_content(source, 'Copied question')
        self._release(source)
        created = self.env['qc.checksheet'].with_user(self.author).editor_create({
            'job_id': self._create_job().id, 'type_id': self.type_general.id,
            'header': 'My Header', 'source_id': source.id,
        })
        checksheet = self.env['qc.checksheet'].browse(created['id'])
        self.assertEqual(checksheet.copied_from_id, source)
        self.assertEqual(checksheet.revision, 0)
        self.assertEqual(len(checksheet.group_ids), 1)
        self.assertIn('Copied question', checksheet.group_ids.item_ids.description)

    def test_panel_sheet_is_created_empty_for_the_form(self):
        created = self.env['qc.checksheet'].with_user(self.author).editor_create({
            'job_id': self._create_job().id, 'type_id': self.type_panel.id, 'header': 'Panel',
        })
        self.assertEqual(created['layout'], 'panel_sticker')
        self.assertFalse(self.env['qc.checksheet'].browse(created['id']).group_ids)

    def test_viewer_cannot_create(self):
        with self.assertRaises(AccessError):
            self.env['qc.checksheet'].with_user(self.viewer).editor_create({
                'job_id': self._create_job().id, 'type_id': self.type_general.id, 'header': 'X',
            })

    def test_action_open_editor_carries_the_sheet(self):
        checksheet = self._sheet()
        action = checksheet.action_open_editor()
        self.assertEqual(action['tag'], 'qc_checksheet.editor')
        self.assertEqual(action['context']['active_id'], checksheet.id)
