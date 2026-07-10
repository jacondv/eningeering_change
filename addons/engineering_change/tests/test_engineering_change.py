from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestEngineeringChange(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Users = cls.env['res.users'].with_context(no_reset_password=True)

        cls.group_internal = cls.env.ref('base.group_user')
        cls.group_user = cls.env.ref('engineering_change.group_ec_user')
        cls.group_engineer = cls.env.ref('engineering_change.group_ec_engineer')
        cls.group_bod = cls.env.ref('engineering_change.group_ec_bod')
        cls.group_manager = cls.env.ref('engineering_change.group_ec_manager')
        cls.group_delete = cls.env.ref('engineering_change.group_ec_delete')

        cls.user_general = Users.create({
            'name': 'General User',
            'login': 'ec_general',
            'email': 'ec_general@example.com',
            'group_ids': [(6, 0, [cls.group_internal.id, cls.group_user.id])],
        })
        cls.user_engineer = Users.create({
            'name': 'Engineer',
            'login': 'ec_engineer',
            'email': 'ec_engineer@example.com',
            'group_ids': [(6, 0, [cls.group_internal.id, cls.group_engineer.id])],
        })
        cls.user_bod = Users.create({
            'name': 'BOD Member',
            'login': 'ec_bod',
            'email': 'ec_bod@example.com',
            'group_ids': [(6, 0, [cls.group_internal.id, cls.group_bod.id])],
        })
        cls.user_manager = Users.create({
            'name': 'Engineering Manager',
            'login': 'ec_manager',
            'email': 'ec_manager@example.com',
            'group_ids': [(6, 0, [cls.group_internal.id, cls.group_manager.id])],
        })
        cls.user_deleter = Users.create({
            'name': 'Cleanup Operator',
            'login': 'ec_deleter',
            'email': 'ec_deleter@example.com',
            'group_ids': [(6, 0, [cls.group_internal.id, cls.group_delete.id])],
        })

    def _create_request(self, request_type='minor', rpn=50):
        return self.env['engineering.change'].with_user(self.user_engineer).create({
            'title': 'Test Change',
            'description': '<p>Description</p>',
            'request_type': request_type,
            'rpn': rpn,
            'engineer_id': self.user_engineer.id,
        })

    def test_submit_requires_valid_rpn(self):
        change = self._create_request(rpn=0)
        with self.assertRaises(UserError):
            change.with_user(self.user_engineer).action_submit()

    def test_minor_change_flow(self):
        change = self._create_request(request_type='minor')
        change.with_user(self.user_engineer).action_submit()
        self.assertEqual(change.state, 'waiting_manager_approval')
        self.assertNotEqual(change.name, 'New')

        change.with_user(self.user_manager).action_manager_approve()
        self.assertEqual(change.state, 'implement')

    def test_dcr_flow_and_dcr_no_generation(self):
        change = self._create_request(request_type='dcr')
        change.with_user(self.user_manager).write({'implement_team_ids': [(6, 0, [self.user_engineer.id])]})
        change.with_user(self.user_engineer).action_submit()
        change.with_user(self.user_manager).action_manager_approve()
        self.assertEqual(change.state, 'bod_review')

        change.with_user(self.user_bod).action_bod_approve()
        self.assertEqual(change.state, 'implement')
        self.assertTrue(change.dcr_no)
        self.assertEqual(change.bod_approver_id, self.user_bod)

    def test_bod_reject_sets_draft_with_reason(self):
        change = self._create_request(request_type='dcr')
        change.with_user(self.user_manager).write({'implement_team_ids': [(6, 0, [self.user_engineer.id])]})
        change.with_user(self.user_engineer).action_submit()
        change.with_user(self.user_manager).action_manager_approve()

        wizard = self.env['engineering.change.reject.wizard'].with_user(self.user_bod).create({
            'change_id': change.id,
            'reject_by': 'bod',
            'reject_reason': 'Not compliant',
        })
        wizard.action_confirm_reject()
        self.assertEqual(change.state, 'draft')
        self.assertEqual(change.reject_reason, 'Not compliant')

    def test_action_close_and_reopen(self):
        change = self._create_request(request_type='minor')
        change.with_user(self.user_engineer).action_submit()
        change.with_user(self.user_manager).action_manager_approve()

        task = self.env['project.task'].with_user(self.user_manager).create({
            'change_id': change.id,
            'name': 'Do the thing',
            'user_ids': [(6, 0, [self.user_general.id])],
        })
        task.with_user(self.user_manager).write({'state': '1_done'})
        # Finishing every task no longer auto-closes the request - Production
        # and Close are always explicit, manual steps.
        self.assertEqual(change.state, 'implement')

        change.with_user(self.user_manager).action_confirm_production()
        self.assertEqual(change.state, 'production')

        change.with_user(self.user_manager).action_close_request()
        self.assertEqual(change.state, 'done')
        self.assertTrue(change.close_date)

        change.with_user(self.user_manager).action_reopen()
        self.assertEqual(change.state, 'production')
        self.assertFalse(change.close_date)

    def test_confirm_production_by_implement_owner(self):
        change = self._create_request(request_type='minor')
        change.with_user(self.user_manager).write({
            'implement_team_ids': [(6, 0, [self.user_engineer.id, self.user_general.id])],
            'implement_owner_id': self.user_general.id,
        })
        change.with_user(self.user_engineer).action_submit()
        change.with_user(self.user_manager).action_manager_approve()

        with self.assertRaises(AccessError):
            change.with_user(self.user_engineer).action_confirm_production()

        change.with_user(self.user_general).action_confirm_production()
        self.assertEqual(change.state, 'production')

    def test_only_manager_can_close_request(self):
        change = self._create_request(request_type='minor')
        change.with_user(self.user_engineer).action_submit()
        change.with_user(self.user_manager).action_manager_approve()
        change.with_user(self.user_manager).action_confirm_production()

        with self.assertRaises(UserError):
            change.with_user(self.user_bod).action_close_request()

        change.with_user(self.user_manager).action_close_request()
        self.assertEqual(change.state, 'done')

    def test_revert_to_previous_state(self):
        change = self._create_request(request_type='minor')
        change.with_user(self.user_engineer).action_submit()
        self.assertEqual(change.state, 'waiting_manager_approval')

        with self.assertRaises(UserError):
            change.with_user(self.user_engineer).action_revert_to_previous_state()

        change.with_user(self.user_manager).action_manager_approve()
        self.assertEqual(change.state, 'implement')

        # Accidentally confirmed Production - Manager steps it back one state.
        change.with_user(self.user_manager).action_confirm_production()
        self.assertEqual(change.state, 'production')
        change.with_user(self.user_manager).action_revert_to_previous_state()
        self.assertEqual(change.state, 'implement')

        change.with_user(self.user_manager).action_revert_to_previous_state()
        self.assertEqual(change.state, 'waiting_manager_approval')

        change.with_user(self.user_manager).action_revert_to_previous_state()
        self.assertEqual(change.state, 'draft')

        with self.assertRaises(UserError):
            # Draft has no previous state.
            change.with_user(self.user_manager).action_revert_to_previous_state()

    def test_revert_to_previous_state_dcr_uses_bod_review(self):
        change = self._create_request(request_type='dcr')
        change.with_user(self.user_manager).write({'implement_team_ids': [(6, 0, [self.user_engineer.id])]})
        change.with_user(self.user_engineer).action_submit()
        change.with_user(self.user_manager).action_manager_approve()
        self.assertEqual(change.state, 'bod_review')

        change.with_user(self.user_bod).action_bod_approve()
        self.assertEqual(change.state, 'implement')

        change.with_user(self.user_manager).action_revert_to_previous_state()
        self.assertEqual(change.state, 'bod_review')

    def test_general_user_can_only_update_status(self):
        change = self._create_request(request_type='minor')
        change.with_user(self.user_engineer).action_submit()
        change.with_user(self.user_manager).action_manager_approve()

        task = self.env['project.task'].with_user(self.user_manager).create({
            'change_id': change.id,
            'name': 'Do the thing',
            'user_ids': [(6, 0, [self.user_general.id])],
        })

        task.with_user(self.user_general).write({'state': '01_in_progress'})
        self.assertEqual(task.state, '01_in_progress')

        with self.assertRaises(AccessError):
            task.with_user(self.user_general).write({'name': 'Renamed by general user'})

    def test_unlink_only_allowed_in_draft(self):
        change = self._create_request(request_type='minor')
        change.with_user(self.user_engineer).action_submit()
        with self.assertRaises(UserError):
            change.with_user(self.user_manager).unlink()

    def test_state_cannot_be_written_directly(self):
        change = self._create_request(request_type='minor')
        # Manager Approve has unconditional base write access to the model, but
        # `state` (and the other workflow-managed fields) may only change as a
        # side effect of the workflow buttons, not via a direct write().
        with self.assertRaises(UserError):
            change.with_user(self.user_manager).write({'state': 'implement'})
        # The workflow methods themselves still work (they set the bypass context).
        change.with_user(self.user_engineer).action_submit()
        self.assertEqual(change.state, 'waiting_manager_approval')

    def test_delete_is_an_independent_capability(self):
        change = self._create_request(request_type='minor')

        # Manager Approve alone no longer includes Delete - the ACL denies it outright.
        with self.assertRaises(AccessError):
            change.with_user(self.user_manager).unlink()

        # A user holding only the Delete group can remove a Draft request, even
        # though they have no Request/Approve rights of their own.
        change.with_user(self.user_deleter).unlink()
        self.assertFalse(change.exists())

    def test_everyone_sees_every_request(self):
        change = self._create_request(request_type='minor')
        for user in (self.user_general, self.user_engineer, self.user_bod, self.user_manager, self.user_deleter):
            self.assertIn(change, self.env['engineering.change'].with_user(user).search([]))

    def test_engineer_content_locked_once_submitted(self):
        change = self._create_request(request_type='minor')
        change.with_user(self.user_engineer).write({'title': 'Still draft, still editable'})

        change.with_user(self.user_engineer).action_submit()
        with self.assertRaises(UserError):
            change.with_user(self.user_engineer).write({'title': 'Too late'})

    def test_manager_cannot_edit_engineer_content(self):
        change = self._create_request(request_type='minor')
        with self.assertRaises(AccessError):
            change.with_user(self.user_manager).write({'title': 'Manager should not touch this'})

    def test_request_type_exception_for_manager(self):
        change = self._create_request(request_type='minor')
        change.with_user(self.user_engineer).action_submit()

        # Manager may still correct the Request Type at the waiting-approval step.
        change.with_user(self.user_manager).write({'request_type': 'dcr'})
        self.assertEqual(change.request_type, 'dcr')

        # But the Engineer alone cannot change it anymore once submitted.
        with self.assertRaises(UserError):
            change.with_user(self.user_engineer).write({'request_type': 'minor'})

    def test_engineer_cannot_edit_manager_fields(self):
        change = self._create_request(request_type='minor')
        with self.assertRaises(AccessError):
            change.with_user(self.user_engineer).write({'implement_team_ids': [(6, 0, [self.user_engineer.id])]})

    def test_default_implement_team_and_owner(self):
        change = self._create_request(request_type='minor')
        self.assertEqual(change.implement_team_ids, self.user_engineer)
        self.assertEqual(change.implement_owner_id, self.user_engineer)

    def test_only_manager_or_owner_can_edit_task_details(self):
        change = self._create_request(request_type='minor')
        change.with_user(self.user_engineer).action_submit()
        change.with_user(self.user_manager).action_manager_approve()
        # Reassign Implement Owner away from the default (the creating engineer)
        # so user_engineer below ends up neither Manager, Owner, nor unrelated.
        change.with_user(self.user_manager).write({
            'implement_team_ids': [(4, self.user_manager.id)],
            'implement_owner_id': self.user_manager.id,
        })

        task = self.env['project.task'].with_user(self.user_manager).create({
            'change_id': change.id,
            'name': 'Do the thing',
            'user_ids': [(6, 0, [self.user_engineer.id])],
        })
        task.with_user(self.user_manager).write({'name': 'Renamed by manager'})
        self.assertEqual(task.name, 'Renamed by manager')

        # Assigned to do the task, but editing its info (not just status/evidence)
        # is Manager/Owner-only - user_engineer here is neither.
        with self.assertRaises(AccessError):
            task.with_user(self.user_engineer).write({'name': 'Renamed by assignee'})

    def test_implement_owner_can_create_edit_and_delete_tasks(self):
        change = self._create_request(request_type='minor')  # owner defaults to user_engineer
        change.with_user(self.user_engineer).action_submit()
        change.with_user(self.user_manager).action_manager_approve()

        task = self.env['project.task'].with_user(self.user_engineer).create({
            'change_id': change.id,
            'name': 'Do the thing',
            'user_ids': [(6, 0, [self.user_general.id])],
        })
        task.with_user(self.user_engineer).write({'name': 'Renamed by owner'})
        self.assertEqual(task.name, 'Renamed by owner')

        task.with_user(self.user_engineer).unlink()
        self.assertFalse(task.exists())

    def test_non_owner_cannot_create_or_delete_task(self):
        change = self._create_request(request_type='minor')  # owner defaults to user_engineer
        change.with_user(self.user_engineer).action_submit()
        change.with_user(self.user_manager).action_manager_approve()

        with self.assertRaises(AccessError):
            self.env['project.task'].with_user(self.user_bod).create({
                'change_id': change.id,
                'name': 'Do the thing',
            })

        task = self.env['project.task'].with_user(self.user_engineer).create({
            'change_id': change.id,
            'name': 'Do the thing',
            'user_ids': [(6, 0, [self.user_bod.id])],
        })
        with self.assertRaises(AccessError):
            task.with_user(self.user_bod).unlink()

    def test_unrelated_user_cannot_write_task(self):
        change = self._create_request(request_type='minor')
        change.with_user(self.user_engineer).action_submit()
        change.with_user(self.user_manager).action_manager_approve()

        task = self.env['project.task'].with_user(self.user_manager).create({
            'change_id': change.id,
            'name': 'Do the thing',
            'user_ids': [(6, 0, [self.user_engineer.id])],
        })
        # user_bod is not the assignee, not the request's engineer, not in the
        # implement team, and not Manager - has no write access at all.
        with self.assertRaises(AccessError):
            task.with_user(self.user_bod).write({'state': '01_in_progress'})

    def test_assignee_can_set_task_done_or_cancelled(self):
        change = self._create_request(request_type='minor')
        change.with_user(self.user_engineer).action_submit()
        change.with_user(self.user_manager).action_manager_approve()

        task = self.env['project.task'].with_user(self.user_manager).create({
            'change_id': change.id,
            'name': 'Do the thing',
            'user_ids': [(6, 0, [self.user_general.id])],
        })
        task.with_user(self.user_general).write({'state': '1_canceled'})
        self.assertEqual(task.state, '1_canceled')

        task.with_user(self.user_general).write({'state': '1_done'})
        self.assertEqual(task.state, '1_done')

    def test_assignee_can_add_and_delete_own_evidence(self):
        change = self._create_request(request_type='minor')
        change.with_user(self.user_engineer).action_submit()
        change.with_user(self.user_manager).action_manager_approve()

        task = self.env['project.task'].with_user(self.user_manager).create({
            'change_id': change.id,
            'name': 'Do the thing',
            'user_ids': [(6, 0, [self.user_general.id])],
        })
        evidence = self.env['engineering.change.action.evidence'].with_user(self.user_general).create({
            'task_id': task.id,
            'description': 'Proof of work',
        })
        self.assertIn(evidence, task.evidence_ids)

        evidence.with_user(self.user_general).unlink()
        self.assertFalse(evidence.exists())

    def test_unrelated_user_cannot_delete_evidence(self):
        change = self._create_request(request_type='minor')
        change.with_user(self.user_engineer).action_submit()
        change.with_user(self.user_manager).action_manager_approve()

        task = self.env['project.task'].with_user(self.user_manager).create({
            'change_id': change.id,
            'name': 'Do the thing',
            'user_ids': [(6, 0, [self.user_general.id])],
        })
        evidence = self.env['engineering.change.action.evidence'].with_user(self.user_general).create({
            'task_id': task.id,
            'description': 'Proof of work',
        })
        # Engineer can see/add evidence on any EC task, but not hard-delete
        # evidence on a task they are not assigned to.
        with self.assertRaises(AccessError):
            evidence.with_user(self.user_engineer).unlink()
