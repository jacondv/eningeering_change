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
        self.assertEqual(data['revision'], 1)
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
            [(r['id'], r['revision']) for r in data['revisions']], [(rev0.id, 1), (rev1.id, 2)])
        old = rev0.editor_load()
        self.assertEqual(data['groups'][0]['line_key'], old['groups'][0]['line_key'])
        self.assertEqual(data['groups'][0]['items'][0]['line_key'], old['groups'][0]['items'][0]['line_key'])
        self.assertTrue(data['groups'][0]['items'][0]['line_key'])

    def test_save_on_a_copied_rev0_keeps_line_keys_of_its_source(self):
        source = self._create_checksheet()
        self._create_content(source, '<p>Step</p>')
        self._release(source)
        copy = self._create_checksheet().with_user(self.author)
        copy._copy_content_from(source)
        payload = self._payload(copy, name='This Machine')
        payload['groups'][0]['items'][0]['description'] = '<p>Changed</p>'

        copy.editor_save(payload)

        self.assertEqual(copy.name, 'This Machine')
        self.assertIn('Changed', copy.group_ids.item_ids.description)
        # Still matched line by line with the source, so the editor can compare them.
        self.assertEqual(copy.group_ids.item_ids.line_key, source.group_ids.item_ids.line_key)

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
        self.assertEqual(old_line.description, 'Initial release')
        self.assertEqual(current_line.description, 'Reworded')
        self.assertEqual(str(current_line.date), '2026-01-15')
        self.assertFalse(current_line.show_in_report)

    def test_load_suggests_the_names_of_internal_users_for_created_by(self):
        portal = new_test_user(self.env, login='qc_editor_portal', groups='base.group_portal')
        names = self._sheet().editor_load()['user_names']
        self.assertIn(self.author.name, names)
        self.assertIn(self.approver.name, names)
        self.assertNotIn(portal.name, names)
        self.assertEqual(len(names), len(set(names)))

    def test_created_by_starts_as_the_user_and_can_be_changed_on_the_current_row(self):
        rev0 = self._sheet()
        rev0.action_submit()
        rev0.with_user(self.approver).action_approve()
        rev1 = rev0.browse(rev0.action_create_revision('First reason')['res_id'])
        old_line, current_line = rev1.history_ids
        self.assertEqual(current_line.created_by, rev1.env.user.name)
        before = old_line.created_by

        payload = self._payload(rev1)
        payload['history'][0]['created_by'] = 'Tampered'
        payload['history'][1]['created_by'] = ' Nguyen Van A '
        rev1.editor_save(payload)
        self.assertEqual(old_line.created_by, before)
        self.assertEqual(current_line.created_by, 'Nguyen Van A')
        self.assertIn('Nguyen Van A', self.env['ir.actions.report']._render_qweb_html(
            'qc_checksheet.report_qc_checksheet_document', rev1.ids)[0].decode())

        # Cleared, it goes back to the user saving.
        payload = self._payload(rev1)
        payload['history'][1]['created_by'] = ''
        rev1.editor_save(payload)
        self.assertEqual(current_line.created_by, rev1.env.user.name)

    def test_created_by_is_not_written_by_hand_on_an_old_row_or_once_locked(self):
        rev0 = self._sheet()
        line = rev0.history_ids
        rev0.action_submit()
        with self.assertRaises(UserError):
            line.with_user(self.author).write({'created_by': 'Someone'})
        rev0.with_user(self.approver).action_approve()
        rev1 = rev0.browse(rev0.action_create_revision('Next')['res_id'])
        with self.assertRaises(UserError):
            rev1.history_ids[0].with_user(self.author).write({'created_by': 'Someone'})
        rev1.history_ids[1].with_user(self.author).write({'created_by': 'Someone'})
        self.assertEqual(rev1.history_ids[1].created_by, 'Someone')

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

    def test_models_offered_match_the_term(self):
        model = self._create_model('M-EDITOR-1')
        self._create_model('OTHER-1')
        results = self.env['qc.checksheet'].with_user(self.author).editor_search_models('M-EDITOR')
        self.assertEqual([result['id'] for result in results], [model.id])

    def test_new_context_previews_the_sheet(self):
        category = self.env['equipment.model.category'].create({'name': 'Category'})
        self.model_za90.family_id = self.env['equipment.model.family'].create({
            'name': 'Family', 'description': 'Zero\nLoader', 'category_id': category.id,
        })
        self._create_job()
        Sheet = self.env['qc.checksheet'].with_user(self.author)
        context = Sheet.editor_new_context(self.model_za90.id, self.type_general.id)
        self.assertEqual(context['number'], 'QC-GE-ZA90')
        self.assertEqual(context['header'], 'Zero Loader')
        self.assertEqual(context['family'], 'Family')
        self.assertEqual(context['job_count'], 1)
        self.assertFalse(context['duplicate_id'])

        existing = self._create_checksheet(model=self.model_za90)
        context = Sheet.editor_new_context(self.model_za90.id, self.type_general.id)
        self.assertEqual(context['duplicate_id'], existing.id)

    def test_new_context_lists_only_released_sources_of_the_same_type(self):
        type_other = self.env['qc.checksheet.type'].create({'name': 'Other', 'code': 'OT', 'layout': 'standard'})
        other_type = self._release(self._create_checksheet(type_other))
        same = self._release(self._create_checksheet())
        self._create_checksheet()
        self._release(self._create_checksheet(self.type_panel))
        sources = self.env['qc.checksheet'].with_user(self.author).editor_new_context(
            self._create_model().id, self.type_general.id)['sources']
        ids = [source['id'] for source in sources]
        self.assertIn(same.id, ids)
        self.assertNotIn(other_type.id, ids)
        self.assertEqual(self.env['qc.checksheet'].browse(ids).type_id, self.type_general)
        self.assertEqual(self.env['qc.checksheet'].browse(ids).mapped('state'), ['released'] * len(ids))

    def test_a_sheet_cannot_be_copied_from_another_type_with_the_same_layout(self):
        type_other = self.env['qc.checksheet.type'].create({'name': 'Other', 'code': 'OT', 'layout': 'standard'})
        other_type = self._release(self._create_checksheet(type_other))
        with self.assertRaises(UserError):
            self._create_checksheet()._copy_content_from(other_type)

    def test_new_context_lists_the_same_product_family_before_other_models(self):
        category = self.env['equipment.model.category'].create({'name': 'Category'})
        Family = self.env['equipment.model.family']
        wanted = Family.create({'name': 'Wanted', 'category_id': category.id})
        elsewhere = Family.create({'name': 'Elsewhere', 'category_id': category.id})
        target = self._create_model(family_id=wanted.id)
        # Created first, so it would sit last by date alone.
        related = self._release(self._create_checksheet(model=self._create_model(family_id=wanted.id)))
        stranger = self._release(self._create_checksheet(model=self._create_model(family_id=elsewhere.id)))
        ids = [source['id'] for source in self.env['qc.checksheet'].with_user(self.author).editor_new_context(
            target.id, self.type_general.id)['sources']]
        self.assertLess(ids.index(related.id), ids.index(stranger.id))

    def test_new_context_sources_can_be_filtered_by_model(self):
        wanted_model = self._create_model('M-FILTER-1')
        wanted = self._release(self._create_checksheet(model=wanted_model))
        self._release(self._create_checksheet())
        sources = self.env['qc.checksheet'].with_user(self.author).editor_new_context(
            self._create_model().id, self.type_general.id, wanted_model.id)['sources']
        self.assertEqual([source['id'] for source in sources], [wanted.id])

    def test_source_models_are_those_with_something_to_copy(self):
        with_released = self._create_model('M-SRC-1')
        self._release(self._create_checksheet(model=with_released))
        self._create_checksheet(model=self._create_model('M-SRC-2'))
        self._release(self._create_checksheet(self.type_panel, model=self._create_model('M-SRC-3')))
        found = self.env['qc.checksheet'].with_user(self.author).editor_search_source_models(
            self.type_general.id, 'M-SRC')
        self.assertEqual([model['id'] for model in found], [with_released.id])

    def test_create_blank_starts_with_one_empty_row(self):
        created = self.env['qc.checksheet'].with_user(self.author).editor_create({
            'model_id': self._create_model().id, 'type_id': self.type_general.id, 'header': 'My Header',
        })
        checksheet = self.env['qc.checksheet'].browse(created['id'])
        self.assertEqual(created['layout'], 'standard')
        self.assertEqual(checksheet.name, 'My Header')
        self.assertEqual(checksheet.revision, 1)
        self.assertEqual(len(checksheet.group_ids), 1)
        self.assertEqual(len(checksheet.group_ids.item_ids), 1)

    def test_create_can_copy_from_a_released_sheet(self):
        source = self._create_checksheet()
        self._create_content(source, 'Copied question')
        self._release(source)
        created = self.env['qc.checksheet'].with_user(self.author).editor_create({
            'model_id': self._create_model().id, 'type_id': self.type_general.id,
            'header': 'My Header', 'source_id': source.id,
        })
        checksheet = self.env['qc.checksheet'].browse(created['id'])
        self.assertEqual(checksheet.copied_from_id, source)
        self.assertEqual(checksheet.revision, 1)
        self.assertEqual(len(checksheet.group_ids), 1)
        self.assertIn('Copied question', checksheet.group_ids.item_ids.description)
        # The editor offers the source as a base to compare with.
        self.assertEqual(checksheet.with_user(self.author).editor_load()['source'], {
            'id': source.id, 'label': f'Copied from {source.reference} Rev 1'})
        self.assertIs(source.editor_load()['source'], False)

    def _start_at(self, start, **extra):
        Checksheet = self.env['qc.checksheet'].with_user(self.author)
        created = Checksheet.editor_create({
            'model_id': self._create_model().id, 'type_id': self.type_general.id, 'header': 'Came from Word',
            'start_rev': start, **extra,
        })
        return Checksheet.browse(created['id'])

    def test_a_sheet_that_exists_on_paper_starts_at_its_own_revision(self):
        sheet = self._start_at(4)
        self.assertEqual((sheet.revision, sheet.state), (4, 'draft'))
        self.assertEqual(sheet.root_id.revision_ids, sheet)
        history = sheet.history_ids.sorted('rev')
        self.assertEqual(history.mapped('rev'), [1, 2, 3, 4])
        self.assertEqual(history.mapped('legacy'), [True] * 3 + [False])
        self.assertEqual(set(history[:3].mapped('description')), {'To be updated'})
        self.assertFalse(any(history[:3].mapped('date')))
        self.assertEqual(history[3].description, 'Initial release')
        self.assertEqual(sheet.change_reason, 'Initial release')
        self.assertEqual(len(sheet.group_ids), 1)

    def test_starting_at_one_changes_nothing(self):
        sheet = self._start_at(1)
        self.assertEqual(sheet.revision, 1)
        self.assertEqual(sheet.history_ids.mapped('legacy'), [False])

    def test_the_start_revision_is_from_1_to_99(self):
        self.assertEqual(self._start_at(99).revision, 99)
        for bad in (-1, 0, 100, '4', 1.5, True):
            with self.assertRaises(UserError, msg=repr(bad)):
                self._start_at(bad)

    def test_only_the_first_sheet_of_a_model_and_type_may_start_above_zero(self):
        model = self._create_model()
        Checksheet = self.env['qc.checksheet'].with_user(self.author)
        self._create_checksheet(model=model)
        with self.assertRaises(UserError):
            Checksheet.editor_create({
                'model_id': model.id, 'type_id': self.type_general.id, 'header': 'X', 'start_rev': 2})

    def test_the_earlier_rows_are_filled_in_by_hand_and_the_next_revision_follows_on(self):
        sheet = self._start_at(3)
        payload = sheet.editor_load()
        by_rev = {line['rev']: line for line in payload['history']}
        by_rev[1].update({'description': 'First issue', 'date': '2023-02-01', 'created_by': 'An', 'approved_by': 'Binh'})
        by_rev[2].update({'description': 'Added step 3', 'date': '2024-03-04', 'created_by': '', 'approved_by': 'Binh'})
        by_rev[3].update({'description': 'Changed limit', 'approved_by': 'Tampered'})
        sheet.editor_save(payload)
        first, second, current = sheet.history_ids.sorted('rev')
        self.assertEqual((first.description, str(first.date), first.created_by, first.approved_by),
                         ('First issue', '2023-02-01', 'An', 'Binh'))
        # Left empty, the author of an earlier Revision stays unknown: it isn't the user saving now.
        self.assertFalse(second.created_by)
        self.assertEqual(current.description, 'Changed limit')
        # The current Revision's Approved By is the system's, as ever.
        self.assertFalse(current.approved_by)
        sheet.sudo().group_ids.unlink()
        self._create_content(sheet)
        sheet.action_submit()
        sheet.with_user(self.approver).action_approve()
        # Released: the rows are locked like any other.
        with self.assertRaises(UserError):
            first.with_user(self.author).write({'description': 'Late edit'})
        new = sheet.browse(sheet.action_create_revision('Next change')['res_id'])
        self.assertEqual(new.revision, 4)
        self.assertEqual(new.history_ids.sorted('rev').mapped('legacy'), [True, True, False, False])
        self.assertEqual(new.history_ids.sorted('rev')[0].approved_by, 'Binh')

    def test_only_a_row_from_before_odoo_takes_approved_by_by_hand(self):
        sheet = self._start_at(2)
        legacy, current = sheet.history_ids.sorted('rev')
        legacy.with_user(self.author).write({'approved_by': 'Binh'})
        self.assertEqual(legacy.approved_by, 'Binh')
        with self.assertRaises(UserError):
            current.with_user(self.author).write({'approved_by': 'Me'})
        with self.assertRaises(UserError):
            legacy.with_user(self.author).write({'legacy': False})

    def test_the_model_page_creates_sheets_at_their_own_revisions(self):
        model = self._create_model()
        created = self.env['qc.checksheet'].with_user(self.author).model_create_sheets(model.id, [
            {'type_id': self.type_general.id, 'header': 'A', 'start_rev': 3},
            {'type_id': self.type_panel.id, 'header': 'B'},
        ])
        revisions = {sheet.type_id: sheet.revision for sheet in self.env['qc.checksheet'].browse([c['id'] for c in created])}
        self.assertEqual(revisions, {self.type_general: 3, self.type_panel: 1})

    def test_panel_sheet_is_created_empty_for_the_form(self):
        created = self.env['qc.checksheet'].with_user(self.author).editor_create({
            'model_id': self._create_model().id, 'type_id': self.type_panel.id, 'header': 'Panel',
        })
        self.assertEqual(created['layout'], 'panel_sticker')
        self.assertFalse(self.env['qc.checksheet'].browse(created['id']).group_ids)

    def test_viewer_cannot_create(self):
        with self.assertRaises(AccessError):
            self.env['qc.checksheet'].with_user(self.viewer).editor_create({
                'model_id': self._create_model().id, 'type_id': self.type_general.id, 'header': 'X',
            })

    def test_a_list_row_opens_a_standard_sheet_on_the_editor_and_a_panel_sheet_on_its_form(self):
        standard = self._sheet()
        action = standard.action_open_default()
        self.assertEqual((action['tag'], action['context']['active_id']), ('qc_checksheet.editor', standard.id))
        panel = self._create_checksheet(self.type_panel)
        action = panel.action_open_default()
        self.assertEqual((action['type'], action['res_model'], action['res_id']), ('ir.actions.act_window', 'qc.checksheet', panel.id))

    def test_action_open_editor_carries_the_sheet(self):
        checksheet = self._sheet()
        action = checksheet.action_open_editor()
        self.assertEqual(action['tag'], 'qc_checksheet.editor')
        self.assertEqual(action['context']['active_id'], checksheet.id)
