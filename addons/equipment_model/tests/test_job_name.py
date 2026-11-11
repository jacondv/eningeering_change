from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import tagged

from .common import EquipmentModelCase


@tagged('post_install', '-at_install')
class TestJobName(EquipmentModelCase):

    def suggest(self, model=None):
        return self.env['project.project'].get_suggested_job_name((model or self.model).id)

    def test_suggests_family_and_next_group_number(self):
        self.assertEqual(self.suggest(), 'TS100-265')

    def test_number_is_shared_across_the_groups_families(self):
        other_family = self.env['equipment.model.family'].create({'name': 'TS200', 'category_id': self.group.id})
        other_model = self.env['equipment.model'].create({'name': 'TS200-A', 'family_id': other_family.id})
        self._job('TS100-265')
        self.assertEqual(self.suggest(other_model), 'TS200-266')

    def test_digits_are_configurable(self):
        self.group.write({'last_job_number': 6, 'job_number_digits': 4})
        self.assertEqual(self.suggest(), 'TS100-0007')

    def test_digits_must_stay_reasonable(self):
        with self.assertRaises(ValidationError):
            self.group.job_number_digits = 0

    def test_suggestion_skips_numbers_already_taken(self):
        self.env.cr.execute("UPDATE equipment_model_category SET last_job_number = 264 WHERE id = %s", [self.group.id])
        self._job('TS100-265')
        self.env.cr.execute("UPDATE equipment_model_category SET last_job_number = 264 WHERE id = %s", [self.group.id])
        self.group.invalidate_recordset()
        self.assertEqual(self.suggest(), 'TS100-266')

    def test_suggestion_skips_numbers_taken_by_other_families_of_the_group(self):
        other_family = self.env['equipment.model.family'].create({'name': 'TS200', 'category_id': self.group.id})
        other_model = self.env['equipment.model'].create({'name': 'TS200-A', 'family_id': other_family.id})
        self._job('TS200-265', model=other_model)
        self.env.cr.execute("UPDATE equipment_model_category SET last_job_number = 264 WHERE id = %s", [self.group.id])
        self.group.invalidate_recordset()
        self.assertEqual(self.suggest(), 'TS100-266')

    def test_counter_filled_from_the_highest_number_in_use(self):
        other_family = self.env['equipment.model.family'].create({'name': 'TS200', 'category_id': self.group.id})
        other_model = self.env['equipment.model'].create({'name': 'TS200-A', 'family_id': other_family.id})
        self._job('TS100-120')
        self._job('TS200-130 (Volvo)', model=other_model)
        self._job('Draft TS100')
        empty_group = self.env['equipment.model.category'].create({'name': 'Test Group 09'})
        set_by_hand = self.env['equipment.model.category'].create({'name': 'Test Group 10', 'last_job_number': 5})
        self.env.cr.execute("UPDATE equipment_model_category SET last_job_number = 0 WHERE id = %s", [self.group.id])
        self.group.invalidate_recordset()
        ahead = self.env['equipment.model.category'].create({'name': 'Test Group 11', 'last_job_number': 400})
        (self.group | empty_group | set_by_hand | ahead)._fill_last_job_numbers()
        self.assertEqual(self.group.last_job_number, 130)
        self.assertEqual(empty_group.last_job_number, 0)
        self.assertEqual(set_by_hand.last_job_number, 5)
        self.assertEqual(ahead.last_job_number, 400, "never lowered")

    def test_model_without_family_uses_its_parents(self):
        child = self.env['equipment.model'].create({'name': 'TS100-A-1', 'parent_id': self.model.id})
        self.assertEqual(self.suggest(child), 'TS100-265')

    def test_model_without_any_family_is_explained(self):
        orphan = self.env['equipment.model'].create({'name': 'Orphan'})
        with self.assertRaisesRegex(UserError, 'no Product Family'):
            self.suggest(orphan)

    def test_saving_the_suggested_name_moves_the_counter(self):
        self._job(self.suggest())
        self.assertEqual(self.group.last_job_number, 265)

    def test_suggestion_alone_moves_nothing(self):
        self.suggest()
        self.assertEqual(self.group.last_job_number, 264)

    def test_an_edited_suggestion_still_counts(self):
        self._job('TS100-265 (Hardware version)')
        self.assertEqual(self.group.last_job_number, 265)

    def test_a_typed_higher_number_moves_the_counter(self):
        self._job('TS100-270')
        self.assertEqual(self.group.last_job_number, 270)

    def test_a_lower_number_leaves_the_counter(self):
        self._job('TS100-250')
        self.assertEqual(self.group.last_job_number, 264)

    def test_a_draft_without_number_leaves_the_counter(self):
        self._job('Draft TS100 for Volvo')
        self._job('TS100 draft')
        self.assertEqual(self.group.last_job_number, 264)

    def test_a_group_that_outgrows_its_digits_keeps_counting(self):
        self.group.last_job_number = 998
        self._job(self.suggest())
        self.assertEqual(self.group.last_job_number, 999)
        self._job('TS100-1000')
        self.assertEqual(self.group.last_job_number, 1000)
        self.assertEqual(self.suggest(), 'TS100-1001')

    def test_templates_do_not_use_up_numbers(self):
        self._job('TS100-265', is_template=True)
        self.assertEqual(self.suggest(), 'TS100-265')

    def test_another_familys_prefix_does_not_count(self):
        self._job('OTHER-300')
        self.assertEqual(self.group.last_job_number, 264)

    def test_renaming_a_draft_to_a_number_moves_the_counter(self):
        job = self._job('Draft for Volvo')
        job.name = 'TS100-266'
        self.assertEqual(self.group.last_job_number, 266)

    def test_setting_the_model_later_moves_the_counter(self):
        job = self.env['project.project'].create({'name': 'TS100-267'})
        self.assertEqual(self.group.last_job_number, 264)
        job.model_id = self.model
        self.assertEqual(self.group.last_job_number, 267)

    def test_templates_never_count(self):
        self._job('TS100-280', is_template=True)
        self.assertEqual(self.group.last_job_number, 264)

    def test_users_without_group_rights_still_move_it(self):
        user = self.env['res.users'].create({
            'name': 'Project only', 'login': 'project_only_em',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id, self.env.ref('project.group_project_manager').id])],
        })
        self.env['project.project'].with_user(user).create({'name': 'TS100-290', 'model_id': self.model.id})
        self.assertEqual(self.group.last_job_number, 290)
