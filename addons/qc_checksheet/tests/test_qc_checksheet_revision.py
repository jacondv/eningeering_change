from psycopg2 import IntegrityError

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests.common import new_test_user, tagged
from odoo.tools import mute_logger

from odoo.addons.qc_checksheet.hooks import grant_default_access

from .common import QcChecksheetCase


@tagged('post_install', '-at_install')
class TestQcChecksheetRevision(QcChecksheetCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.author = new_test_user(
            cls.env, login='qc_author', groups='base.group_user,qc_checksheet.group_qc_author')
        cls.approver = new_test_user(
            cls.env, login='qc_approver', groups='base.group_user,qc_checksheet.group_qc_approver')
        cls.viewer = new_test_user(cls.env, login='qc_viewer', groups='base.group_user')
        cls.admin = new_test_user(
            cls.env, login='qc_admin', groups='base.group_user,qc_checksheet.group_qc_admin')

    def _draft_as_author(self, description='Check oil level'):
        checksheet = self._create_checksheet().with_user(self.author)
        self._create_content(checksheet, description)
        return checksheet

    def _released_as_author(self):
        checksheet = self._draft_as_author()
        checksheet.action_submit()
        checksheet.with_user(self.approver).action_approve()
        return checksheet

    def _new_revision(self, checksheet, reason='Change limit'):
        action = checksheet.action_create_revision(reason)
        return self.env['qc.checksheet'].with_user(checksheet.env.user).browse(action['res_id'])

    def _render(self, checksheet):
        report = self.env.ref('qc_checksheet.action_report_qc_checksheet')
        return report.sudo()._render_qweb_html(report.report_name, checksheet.ids)[0].decode()

    # Identity

    def test_number_comes_from_type_and_model(self):
        checksheet = self._create_checksheet()
        self.assertEqual(checksheet.reference, 'QC-GE-ZA90')
        self.assertEqual(checksheet.revision, 0)
        self.assertEqual(checksheet.state, 'draft')
        self.assertEqual(checksheet.root_id, checksheet)
        self.assertEqual(checksheet.history_ids.mapped('rev'), [0])

    def test_number_is_kept_when_model_is_renamed(self):
        checksheet = self._create_checksheet()
        self.model_za90.name = 'ZA95'
        self.assertEqual(checksheet.reference, 'QC-GE-ZA90')
        self.assertEqual(checksheet.machine_model, 'ZA95')

    def test_number_needs_a_job_with_a_model(self):
        with self.assertRaises(UserError):
            self.env['qc.checksheet'].create({'name': 'X', 'type_id': self.type_general.id})
        job = self.env['project.project'].create({'name': 'J-NO-MODEL'})
        with self.assertRaises(UserError):
            self._create_checksheet(job=job)

    def test_one_sheet_per_type_per_job(self):
        job = self._create_job()
        self._create_checksheet(job=job)
        self._create_checksheet(self.type_panel, job=job)
        with mute_logger('odoo.sql_db'), self.assertRaises(IntegrityError):
            self._create_checksheet(job=job)
            self.env.flush_all()

    def test_machine_identity_comes_from_the_job(self):
        partner = self.env['res.partner'].create({'name': 'ACME Co'})
        job = self._create_job(machine_serial='SN-1', engine_serial='EN-1', partner_id=partner.id)
        checksheet = self._create_checksheet(job=job)
        self.assertEqual(checksheet.machine_serial, 'SN-1')
        self.assertEqual(checksheet.engine_number, 'EN-1')
        self.assertEqual(checksheet.customer, 'ACME Co')
        self.assertEqual(checksheet.machine_model, 'ZA90')

    def test_job_and_type_cannot_change_once_set(self):
        checksheet = self._create_checksheet().with_user(self.author)
        with self.assertRaises(UserError):
            checksheet.write({'job_number': self._create_job('J-OTHER').id})
        with self.assertRaises(UserError):
            checksheet.write({'type_id': self.type_panel.id})

    # Workflow

    def test_submit_needs_content(self):
        checksheet = self._create_checksheet().with_user(self.author)
        with self.assertRaises(UserError):
            checksheet.action_submit()

    def test_recall_returns_to_draft_without_a_new_rev(self):
        checksheet = self._draft_as_author()
        checksheet.action_submit()
        self.assertEqual(checksheet.state, 'review')
        checksheet.action_recall()
        self.assertEqual(checksheet.state, 'draft')
        self.assertEqual(checksheet.revision, 0)
        # Editable again, then can be submitted again.
        checksheet.group_ids.write({'name': 'Corrected'})
        checksheet.action_submit()
        self.assertEqual(checksheet.state, 'review')

    def test_recall_impossible_after_approval(self):
        checksheet = self._released_as_author()
        with self.assertRaises(UserError):
            checksheet.action_recall()

    def test_reject_needs_a_reason_and_keeps_rev(self):
        checksheet = self._draft_as_author()
        checksheet.action_submit()
        as_approver = checksheet.with_user(self.approver)
        with self.assertRaises(UserError):
            as_approver.action_reject('  ')
        as_approver.action_reject('Wrong limit')
        self.assertEqual(checksheet.state, 'draft')
        self.assertEqual(checksheet.reject_reason, 'Wrong limit')
        self.assertEqual(checksheet.revision, 0)

    def test_approve_needs_approver_group(self):
        checksheet = self._draft_as_author()
        checksheet.action_submit()
        with self.assertRaises(AccessError):
            checksheet.action_approve()

    def test_approver_can_approve_own_submission(self):
        both = new_test_user(
            self.env, login='qc_both',
            groups='base.group_user,qc_checksheet.group_qc_author,qc_checksheet.group_qc_approver')
        checksheet = self._create_checksheet().with_user(both)
        self._create_content(checksheet)
        checksheet.action_submit()
        self.assertIn(both, checksheet.sudo().activity_ids.user_id)
        checksheet.action_approve()
        self.assertEqual(checksheet.state, 'released')
        self.assertEqual(checksheet.approved_by_id, both)

    def test_approve_fills_history_and_clears_activities(self):
        checksheet = self._draft_as_author()
        checksheet.action_submit()
        self.assertIn(self.approver, checksheet.sudo().activity_ids.user_id)
        checksheet.with_user(self.approver).action_approve()
        self.assertEqual(checksheet.state, 'released')
        self.assertEqual(checksheet.approved_by_id, self.approver)
        self.assertEqual(checksheet.history_ids.approved_by, self.approver.name)
        self.assertTrue(checksheet.history_ids.date)
        self.assertFalse(checksheet.sudo().activity_ids)

    def test_status_cannot_be_written_directly(self):
        checksheet = self._draft_as_author()
        with self.assertRaises(UserError):
            checksheet.write({'state': 'released'})
        with self.assertRaises(UserError):
            checksheet.write({'revision': 5})
        with self.assertRaises(UserError):
            self.env['qc.checksheet'].with_user(self.author).create({
                'name': 'X', 'type_id': self.type_general.id,
                'job_number': self._create_job().id, 'state': 'released',
            })

    # Locking

    def test_released_content_is_locked(self):
        checksheet = self._released_as_author()
        group = checksheet.group_ids
        with self.assertRaises(UserError):
            checksheet.write({'name': 'Changed'})
        with self.assertRaises(UserError):
            group.write({'name': 'Changed'})
        with self.assertRaises(UserError):
            group.item_ids.write({'acceptance': 'Changed'})
        with self.assertRaises(UserError):
            group.item_ids.unlink()
        with self.assertRaises(UserError):
            self.env['qc.checksheet.group'].with_user(self.author).create({
                'checksheet_id': checksheet.id, 'name': 'New',
            })
        with self.assertRaises(UserError):
            checksheet.history_ids.write({'show_in_report': False})

    def test_panel_and_image_lines_are_locked_too(self):
        checksheet = self._create_checksheet(self.type_panel).with_user(self.author)
        line = self.env['qc.checksheet.panel.line'].with_user(self.author).create({
            'checksheet_id': checksheet.id, 'part_number': 'PN-1',
        })
        image_group = self.env['qc.checksheet.image.group'].with_user(self.author).create({
            'checksheet_id': checksheet.id, 'name': 'Overview',
            'image_line_ids': [(0, 0, {'description': 'Front'})],
        })
        checksheet.action_submit()
        with self.assertRaises(UserError):
            line.write({'part_number': 'PN-2'})
        with self.assertRaises(UserError):
            image_group.write({'name': 'Changed'})
        with self.assertRaises(UserError):
            image_group.image_line_ids.write({'description': 'Changed'})

    def test_review_is_locked_until_recalled(self):
        checksheet = self._draft_as_author()
        checksheet.action_submit()
        with self.assertRaises(UserError):
            checksheet.group_ids.write({'name': 'Changed'})

    def test_check_date_stays_editable_on_a_released_sheet(self):
        checksheet = self._released_as_author()
        checksheet.write({'check_date': '2026-11-05'})
        self.assertEqual(str(checksheet.check_date), '2026-11-05')

    def test_show_in_report_is_editable_only_in_draft(self):
        checksheet = self._draft_as_author()
        checksheet.history_ids.write({'show_in_report': False})
        self.assertFalse(checksheet.history_ids.show_in_report)
        checksheet.action_submit()
        with self.assertRaises(UserError):
            checksheet.history_ids.write({'show_in_report': True})

    def test_inventor_import_is_locked_on_a_released_sheet(self):
        checksheet = self._create_checksheet(self.type_panel).with_user(self.author)
        self.env['qc.checksheet.panel.line'].with_user(self.author).create({
            'checksheet_id': checksheet.id, 'part_number': 'PN-1',
        })
        checksheet.action_submit()
        bom = self.env['inventor.bom'].create({'model': 'ZA90', 'bom_type': 'panel_sticker'})
        wizard = self.env['qc.checksheet.inventor.import.wizard'].with_user(self.author).create({
            'checksheet_id': checksheet.id, 'bom_id': bom.id,
        })
        with self.assertRaises(UserError):
            wizard.action_import()

    # Revisions

    def test_new_revision_needs_a_reason_and_a_released_sheet(self):
        checksheet = self._draft_as_author()
        with self.assertRaises(UserError):
            checksheet.action_create_revision('Change limit')
        checksheet.action_submit()
        checksheet.with_user(self.approver).action_approve()
        with self.assertRaises(UserError):
            checksheet.action_create_revision('   ')

    def test_old_revision_stays_current_until_new_one_is_approved(self):
        rev0 = self._released_as_author()
        rev1 = self._new_revision(rev0)

        self.assertEqual(rev1.revision, 1)
        self.assertEqual(rev1.state, 'draft')
        self.assertEqual(rev1.reference, rev0.reference)
        self.assertEqual(rev1.root_id, rev0)
        self.assertEqual(rev1.previous_revision_id, rev0)
        self.assertEqual(rev0.state, 'released')
        self.assertEqual(rev0.revision_count, 2)

        rev1.action_submit()
        self.assertEqual(rev0.state, 'released')
        rev1.with_user(self.approver).action_approve()
        self.assertEqual(rev1.state, 'released')
        self.assertEqual(rev0.state, 'superseded')

    def test_old_revision_content_is_independent(self):
        rev0 = self._released_as_author()
        rev1 = self._new_revision(rev0)
        rev1.group_ids.item_ids.write({'acceptance': '<p>Changed in Rev 1</p>'})
        self.assertIn('No leak', rev0.group_ids.item_ids.acceptance)
        self.assertIn('Changed in Rev 1', rev1.group_ids.item_ids.acceptance)

    def test_line_keys_survive_a_new_revision(self):
        rev0 = self._released_as_author()
        rev1 = self._new_revision(rev0)
        self.assertTrue(rev0.group_ids.line_key)
        self.assertEqual(rev1.group_ids.line_key, rev0.group_ids.line_key)
        self.assertEqual(rev1.group_ids.item_ids.line_key, rev0.group_ids.item_ids.line_key)
        self.assertNotEqual(rev1.group_ids.id, rev0.group_ids.id)

    def test_new_lines_get_their_own_key(self):
        checksheet = self._draft_as_author()
        other = self._create_content(checksheet, 'Other')
        self.assertNotEqual(other.line_key, checksheet.group_ids[0].line_key)

    def test_panel_and_image_lines_carry_over(self):
        source = self._create_checksheet(self.type_panel).with_user(self.author)
        line = self.env['qc.checksheet.panel.line'].with_user(self.author).create({
            'checksheet_id': source.id, 'part_number': 'PN-1',
        })
        image_group = self.env['qc.checksheet.image.group'].with_user(self.author).create({
            'checksheet_id': source.id, 'name': 'Overview',
            'image_line_ids': [(0, 0, {'description': 'Front'})],
        })
        source.action_submit()
        source.with_user(self.approver).action_approve()

        rev1 = self._new_revision(source)
        self.assertEqual(rev1.panel_line_ids.part_number, 'PN-1')
        self.assertEqual(rev1.panel_line_ids.line_key, line.line_key)
        self.assertEqual(rev1.image_group_ids.line_key, image_group.line_key)
        self.assertEqual(rev1.image_group_ids.image_line_ids.line_key, image_group.image_line_ids.line_key)

    def test_only_one_revision_in_progress(self):
        rev0 = self._released_as_author()
        self._new_revision(rev0)
        with self.assertRaises(UserError):
            rev0.action_create_revision('Another one')

    def test_discarded_draft_does_not_burn_a_rev_number(self):
        rev0 = self._released_as_author()
        rev1 = self._new_revision(rev0)
        rev1.unlink()
        self.assertTrue(rev0.exists())
        self.assertEqual(rev0.state, 'released')
        self.assertEqual(self._new_revision(rev0).revision, 1)

    def test_history_records_each_revision(self):
        rev0 = self._released_as_author()
        rev1 = self._new_revision(rev0, 'Raise pressure limit')
        self.assertEqual(rev1.history_ids.mapped('rev'), [0, 1])
        self.assertEqual(rev1.history_ids[1].description, 'Raise pressure limit')
        self.assertEqual(rev1.history_ids[1].created_by, self.author.name)
        self.assertFalse(rev1.history_ids[1].approved_by)
        # The old Revision's own history stops at itself.
        self.assertEqual(rev0.history_ids.mapped('rev'), [0])

    def test_history_rev_does_not_shift_when_a_row_is_removed(self):
        rev0 = self._released_as_author()
        rev1 = self._new_revision(rev0)
        rev1.sudo().history_ids[0].unlink()
        self.assertEqual(rev1.history_ids.mapped('rev'), [1])

    def test_open_current_revision_from_an_old_one(self):
        rev0 = self._released_as_author()
        rev1 = self._new_revision(rev0)
        rev1.action_submit()
        rev1.with_user(self.approver).action_approve()
        self.assertEqual(rev0.action_open_current_revision()['res_id'], rev1.id)
        self.assertEqual(rev0.action_view_revisions()['domain'], [('root_id', '=', rev0.id)])

    # Copied Rev 0

    def _copied_rev0(self):
        source = self._released_as_author()
        copy = self._create_checksheet().with_user(self.author)
        copy._copy_content_from(source)
        return source, copy

    def test_copied_rev0_starts_with_the_source_content(self):
        source, copy = self._copied_rev0()
        self.assertEqual(copy.group_ids.mapped('name'), source.group_ids.mapped('name'))
        self.assertEqual(copy.group_ids.item_ids.mapped('description'), source.group_ids.item_ids.mapped('description'))
        # Same line keys, so the copy can be compared with its source.
        self.assertEqual(copy.group_ids.mapped('line_key'), source.group_ids.mapped('line_key'))
        self.assertEqual(copy.group_ids.item_ids.mapped('line_key'), source.group_ids.item_ids.mapped('line_key'))

    def test_copied_rev0_can_be_edited_like_any_draft(self):
        source, copy = self._copied_rev0()
        copy.group_ids.item_ids.write({'acceptance': '<p>Changed for this machine</p>'})
        self.env['qc.checksheet.group'].with_user(self.author).create({'checksheet_id': copy.id, 'name': 'New'})
        copy.write({'name': 'This Machine', 'remarks': 'Changed'})
        self.assertIn('Changed for this machine', copy.group_ids.item_ids.acceptance)
        self.assertEqual(len(copy.group_ids), 2)
        # The source is left as it was.
        self.assertNotIn('Changed for this machine', source.group_ids.item_ids.acceptance)
        self.assertEqual(copy.copied_from_id, source)

    def test_copied_rev0_still_locks_once_submitted(self):
        _source, copy = self._copied_rev0()
        copy.action_submit()
        with self.assertRaisesRegex(UserError, 'locked'):
            copy.group_ids.item_ids.write({'acceptance': '<p>Changed</p>'})

    # PDF

    def test_old_revision_prints_its_own_content_with_a_warning(self):
        rev0 = self._released_as_author()
        rev1 = self._new_revision(rev0, 'Raise pressure limit')
        rev1.group_ids.item_ids.write({'acceptance': '<p>Changed in Rev 1</p>'})
        rev1.action_submit()
        rev1.with_user(self.approver).action_approve()

        html = self._render(rev0)
        self.assertIn('SUPERSEDED', html)
        self.assertIn('No leak', html)
        self.assertNotIn('Changed in Rev 1', html)
        self.assertNotIn('Raise pressure limit', html)

        html = self._render(rev1)
        self.assertNotIn('SUPERSEDED', html)
        self.assertNotIn('NOT FOR USE', html)
        self.assertIn('Changed in Rev 1', html)
        self.assertIn('Raise pressure limit', html)

    def test_draft_prints_with_a_warning(self):
        self.assertIn('NOT FOR USE', self._render(self._draft_as_author()))

    def test_footer_keeps_the_real_rev_when_its_history_row_is_hidden(self):
        rev0 = self._released_as_author()
        rev1 = self._new_revision(rev0, 'Secret row')
        rev1.history_ids[1].write({'show_in_report': False})
        html = self._render(rev1)
        self.assertNotIn('Secret row', html)
        self.assertRegex(html, r'Revision:\s*<span>1</span>')

    def test_report_prints_name_as_header_and_type_name_below(self):
        html = self._render(self._create_checksheet(name='Pre Delivery'))
        self.assertIn('PRE DELIVERY', html)
        self.assertIn('GENERAL CHECK SHEET', html)

    def test_name_is_required(self):
        with self.assertRaises(Exception):
            self.env['qc.checksheet'].create({
                'type_id': self.type_general.id, 'job_number': self._create_job().id,
            })
            self.env.flush_all()

    def test_report_shows_rev_zero_job_and_model(self):
        checksheet = self._released_as_author()
        html = self._render(checksheet)
        self.assertRegex(html, r'Revision:\s*<span>0</span>')
        self.assertIn('QC-GE-ZA90', html)
        self.assertIn('J-TEST', html)
        self.assertIn('ZA90</span>', html)

    def test_report_prints_approver_and_revision_history_title(self):
        checksheet = self._released_as_author()
        html = self._render(checksheet)
        self.assertIn('QC Check Sheet Revision History', html)
        self.assertNotIn('Template History', html)
        self.assertIn(self.approver.name, html)

    # Header

    def _family_with_description(self, description):
        category = self.env['equipment.model.category'].create({'name': 'Category'})
        return self.env['equipment.model.family'].create({
            'name': 'Family', 'description': description, 'category_id': category.id,
        })

    def test_header_comes_from_family_description(self):
        self.model_za90.family_id = self._family_with_description('Zero Emission\nLoader')
        sheet = self.env['qc.checksheet'].new({'job_number': self._create_job().id})
        sheet._onchange_job_number()
        self.assertEqual(sheet.name, 'Zero Emission Loader')

    def test_header_stays_empty_without_family_description(self):
        sheet = self.env['qc.checksheet'].new({'job_number': self._create_job().id})
        sheet._onchange_job_number()
        self.assertFalse(sheet.name)

    def test_header_typed_by_the_user_is_kept(self):
        self.model_za90.family_id = self._family_with_description('Loader')
        sheet = self.env['qc.checksheet'].new({'job_number': self._create_job().id, 'name': 'My Header'})
        sheet._onchange_job_number()
        self.assertEqual(sheet.name, 'My Header')

    def test_header_follows_a_corrected_job(self):
        self.model_za90.family_id = self._family_with_description('Loader')
        other_model = self.env['equipment.model'].create({
            'name': 'ZB10', 'family_id': self._family_with_description('Excavator').id,
        })
        sheet = self.env['qc.checksheet'].new({'job_number': self._create_job().id})
        sheet._onchange_job_number()
        sheet.job_number = self._create_job(model=other_model)
        sheet._onchange_job_number()
        self.assertEqual(sheet.name, 'Excavator')

    def test_header_stays_editable_and_is_not_overwritten_by_the_family(self):
        family = self._family_with_description('Loader')
        self.model_za90.family_id = family
        checksheet = self._create_checksheet(name='Loader')
        checksheet.with_user(self.author).write({'name': 'Edited'})
        family.description = 'Changed Later'
        self.assertEqual(checksheet.name, 'Edited')

    def test_user_without_project_access_can_create_and_print(self):
        self.model_za90.family_id = self._family_with_description('Loader')
        job = self._create_job()
        Sheet = self.env['qc.checksheet'].with_user(self.author)
        new_sheet = Sheet.new({'job_number': job.id})
        new_sheet._onchange_job_number()
        checksheet = Sheet.create({
            'name': new_sheet.name, 'type_id': self.type_general.id, 'job_number': job.id,
        })
        self.assertEqual(checksheet.reference, 'QC-GE-ZA90')
        report = self.env.ref('qc_checksheet.action_report_qc_checksheet')
        html = report.with_user(self.viewer)._render_qweb_html(report.report_name, checksheet.ids)[0].decode()
        self.assertIn(job.name, html)

    # Revision History

    def test_date_defaults_to_today_and_stays_as_edited(self):
        rev0 = self._released_as_author()
        rev1 = self._new_revision(rev0)
        line = rev1.history_ids[1]
        self.assertEqual(line.date, fields.Date.context_today(line))
        line.write({'date': '2026-01-15', 'description': 'Reworded'})
        self.assertEqual(rev1.change_reason, 'Reworded')
        rev1.action_submit()
        rev1.with_user(self.approver).action_approve()
        self.assertEqual(str(line.date), '2026-01-15')
        self.assertEqual(line.description, 'Reworded')

    def test_approve_fills_a_date_left_empty(self):
        checksheet = self._draft_as_author()
        checksheet.history_ids.write({'date': False})
        checksheet.action_submit()
        checksheet.with_user(self.approver).action_approve()
        self.assertTrue(checksheet.history_ids.date)

    def test_only_the_current_row_is_editable_in_draft(self):
        rev0 = self._released_as_author()
        rev1 = self._new_revision(rev0)
        old_line, current_line = rev1.history_ids
        with self.assertRaises(UserError):
            old_line.write({'description': 'Rewritten'})
        with self.assertRaises(UserError):
            old_line.write({'date': '2026-01-15'})
        current_line.write({'description': 'Reworded', 'date': '2026-01-15'})
        self.assertEqual(current_line.description, 'Reworded')

    def test_current_row_is_locked_after_submit(self):
        checksheet = self._draft_as_author()
        checksheet.action_submit()
        with self.assertRaises(UserError):
            checksheet.history_ids.write({'description': 'Rewritten'})

    def test_submit_needs_a_description(self):
        checksheet = self._draft_as_author()
        checksheet.history_ids.write({'description': False})
        with self.assertRaises(UserError):
            checksheet.action_submit()

    # Access

    def test_default_access_can_be_removed_for_one_user(self):
        author_group = self.env.ref('qc_checksheet.group_qc_author')
        new_user = self.env['res.users'].create({'name': 'New Hire', 'login': 'qc_new_hire'})
        self.assertIn(author_group, new_user.all_group_ids)

        new_user.write({'group_ids': [(3, author_group.id)]})
        self.assertFalse(new_user.has_group('qc_checksheet.group_qc_author'))
        self.assertTrue(new_user.has_group('qc_checksheet.group_qc_user'))

    def test_default_access_reaches_administrators(self):
        admin_user = self.env['res.users'].create({
            'name': 'Admin Role', 'login': 'qc_admin_role',
            'group_ids': [(6, 0, self.env.ref('base.group_system').ids)],
        })
        self.assertFalse(admin_user.has_group('qc_checksheet.group_qc_author'))
        grant_default_access(self.env)
        self.assertTrue(admin_user.has_group('qc_checksheet.group_qc_author'))

    def test_approver_is_not_a_default(self):
        new_user = self.env['res.users'].create({'name': 'New Hire', 'login': 'qc_new_hire'})
        self.assertFalse(new_user.has_group('qc_checksheet.group_qc_approver'))

    def test_viewer_can_read_and_print_only(self):
        checksheet = self._draft_as_author()
        as_viewer = checksheet.with_user(self.viewer)
        self.assertEqual(as_viewer.reference, 'QC-GE-ZA90')
        with self.assertRaises(AccessError):
            as_viewer.write({'name': 'Changed'})
        with self.assertRaises(AccessError):
            as_viewer.action_submit()
        with self.assertRaises(AccessError):
            self.env['qc.checksheet'].with_user(self.viewer).create({
                'name': 'X', 'type_id': self.type_general.id, 'job_number': self._create_job().id,
            })

    def test_author_can_delete_a_draft_but_not_an_issued_sheet(self):
        self._draft_as_author().unlink()
        with self.assertRaises(UserError):
            self._released_as_author().unlink()

    def test_admin_deletes_an_issued_sheet_only_as_a_whole(self):
        rev0 = self._released_as_author()
        rev1 = self._new_revision(rev0)
        rev1.action_submit()
        rev1.with_user(self.approver).action_approve()
        with self.assertRaises(UserError):
            rev1.with_user(self.admin).unlink()
        (rev0 | rev1).with_user(self.admin).unlink()
        self.assertFalse(rev0.exists())

    def test_only_admin_manages_types(self):
        with self.assertRaises(AccessError):
            self.env['qc.checksheet.type'].with_user(self.author).create({'name': 'X', 'code': 'XX'})
        new_type = self.env['qc.checksheet.type'].with_user(self.admin).create({'name': 'Hydraulic', 'code': 'HY'})
        self.assertEqual(self._create_checksheet(new_type).reference, 'QC-HY-ZA90')

    def test_layout_of_a_used_type_cannot_change(self):
        self._create_checksheet()
        with self.assertRaises(UserError):
            self.type_general.write({'layout': 'panel_sticker'})
