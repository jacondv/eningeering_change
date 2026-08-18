from odoo import _, api, fields, models
from odoo.exceptions import AccessError

DONE_STATES = ('1_done', '1_canceled')


class ProjectTask(models.Model):
    """Engineering Change actions/tasks are implemented as regular project.task
    records (reusing the Project app's assignees, deadline, stage and kanban
    board), tagged with a `change_id` back-reference. All the behavior below
    only kicks in for tasks linked to an Engineering Change request; plain
    project tasks (change_id empty) are left untouched.
    """
    _inherit = 'project.task'

    change_id = fields.Many2one('engineering.change', string='Engineering Change',
                                 ondelete='cascade', index=True)
    manager_id = fields.Many2one('res.users', string='Manager', tracking=True,
                                  default=lambda self: self._default_ec_manager_id())
    affected_model_ids = fields.Many2many(
        'equipment.model', 'engineering_change_action_affected_model_rel',
        'task_id', 'model_id', string='Impacted Models')
    affected_project_ids = fields.Many2many(
        'project.project', 'engineering_change_action_affected_project_rel',
        'task_id', 'project_id', string='Impacted Job Numbers',
        domain=[('is_ec_project', '=', False)],
        help="Concrete customer Job Numbers (Projects) this action affects - "
             "excludes the container Projects auto-created for Engineering "
             "Change requests themselves, only real production jobs.")
    is_overdue = fields.Boolean(compute='_compute_is_overdue', store=True)
    can_edit_ec_task_details = fields.Boolean(compute='_compute_can_edit_ec_task_details')
    can_assign_ec_task = fields.Boolean(compute='_compute_can_edit_ec_task_details')

    # Fields an EC task's own assignee may touch without being Manager Approve
    # or Implement Owner. Kept as a class constant (same style as ENGINEER_FIELDS
    # / MANAGER_FIELDS on engineering.change) so the "what" is declared once and
    # reused by both the write guard and its error message.
    ASSIGNEE_EDITABLE_FIELDS = frozenset({
        'state',
        'evidence_ids',
        'affected_model_ids',
        'affected_project_ids',
        'task_type',
        'timesheet_ids',
        # written automatically by project.task's own write() as a side effect
        # of a state change - not something the user is choosing to set.
        'date_last_stage_update',
    })

    # ------------------------------------------------------------
    # Computed fields / defaults
    # ------------------------------------------------------------
    def _default_ec_manager_id(self):
        change_id = self.env.context.get('default_change_id')
        if change_id:
            change = self.env['engineering.change'].browse(change_id)
            if change.bod_approver_id:
                return change.bod_approver_id.id
        return self.env.user.id

    @api.depends('change_id.implement_owner_id', 'change_id.implement_team_ids')
    def _compute_can_edit_ec_task_details(self):
        """Drives the readonly state of the standard task fields shown on
        the EC task form (see `view_engineering_change_action_form`), so a
        plain assignee sees them as readonly instead of editing them only to
        have the whole save rejected by `_check_ec_write_access`.

        can_assign_ec_task is the narrower case: an Implement Team member who
        isn't Owner/Manager can't edit the rest of that readonly group, but
        per `_check_ec_write_access` they CAN still set `user_ids` (assign the
        task) - without this, the field would stay readonly in the UI even
        though the write itself would be accepted server-side.
        """
        is_manager = self._is_ec_manager()
        for rec in self:
            rec.can_edit_ec_task_details = not rec.change_id or rec._is_ec_owner_or_manager(is_manager)
            rec.can_assign_ec_task = rec.can_edit_ec_task_details or rec._is_ec_team_member()

    @api.depends('date_deadline', 'state')
    def _compute_is_overdue(self):
        today = fields.Date.context_today(self)
        for rec in self:
            deadline = rec.date_deadline and fields.Date.to_date(rec.date_deadline)
            rec.is_overdue = bool(
                rec.change_id and deadline and deadline < today and rec.state not in DONE_STATES)

    # ------------------------------------------------------------
    # Permission checks
    # ------------------------------------------------------------
    @api.model
    def _is_ec_manager(self):
        """Manager Approve holders have unrestricted access to every EC task."""
        return self.env.user.has_group('engineering_change.group_ec_manager')

    def _check_ec_create_access(self, change, is_manager=None):
        """Guard creating an EC task: Manager Approve, `change`'s Implement
        Owner, or any member of its Implement Team may add actions to it -
        the whole team is doing the work, not just its Owner.

        Enforced here in Python rather than left to ir.rule alone: the core
        `project` module ships its own permissive rules for tasks with no
        project_id (e.g. "Project: See private tasks", "...employees: Full
        access to own private task only") granting create/unlink to any
        internal user. ir.rule domains are OR'd together across every
        installed module, so those pre-existing rules would silently override
        any narrower domain declared on our side - only a hard Python check
        can actually restrict below what they already allow.

        :param is_manager: pass the already-computed result of `_is_ec_manager()`
            when checking several records/vals in a loop, to avoid re-querying
            group membership for each one.
        """
        if is_manager is None:
            is_manager = self._is_ec_manager()
        if is_manager or self.env.user in (change.implement_owner_id | change.implement_team_ids):
            return
        raise AccessError(_(
            "Only the Manager or a member of the Implement Team can create "
            "actions/tasks for this request."))

    def _check_ec_delete_access(self, change, is_manager=None):
        """Guard deleting an EC task: only Manager Approve or `change`'s own
        Implement Owner - narrower than create access on purpose, so a
        regular team member can add their own actions but not remove
        someone else's. See _check_ec_create_access for why this is
        enforced in Python rather than left to ir.rule alone."""
        if is_manager is None:
            is_manager = self._is_ec_manager()
        if is_manager or change.implement_owner_id == self.env.user:
            return
        raise AccessError(_(
            "Only the Manager or the request's Implement Owner can delete "
            "actions/tasks for this request."))

    def _is_ec_owner_or_manager(self, is_manager=None):
        """True if the current user has unrestricted edit access to this EC
        task: Manager Approve, or the parent request's Implement Owner."""
        self.ensure_one()
        if is_manager is None:
            is_manager = self._is_ec_manager()
        return is_manager or self.change_id.implement_owner_id == self.env.user

    def _get_or_create_ec_project(self, change):
        """Find-or-create the project.project named after `change`'s Request
        No, so its actions/tasks land under a real project instead of
        defaulting to Private (no project_id).

        If `change` already has its own `project_id` (set on Submit, see
        `EngineeringChange._link_ec_project`), reuse it directly. Otherwise
        (an action created while the request is still Draft, named "New")
        fall back to finding/creating one by the request's current name -
        `_link_ec_project` reconciles these onto the real project once the
        request is actually submitted.

        sudo(): a plain assignee allowed to create an EC task (see
        `_check_ec_create_access`) may not otherwise have search/create
        rights on project.project.
        """
        if change.project_id:
            return change.project_id
        Project = self.env['project.project'].sudo()
        project = Project.search([('name', '=', change.name)], limit=1)
        if not project:
            project = Project.create({'name': change.name})
        return project

    def _is_ec_team_member(self):
        """True if the current user is a member of this task's parent
        request's Implement Team (not necessarily its Owner) - see
        _check_ec_write_access, where this earns write access to `user_ids`
        specifically (assigning the task to someone) on top of the usual
        ASSIGNEE_EDITABLE_FIELDS."""
        self.ensure_one()
        return self.env.user in self.change_id.implement_team_ids

    def _check_ec_write_access(self, vals, is_manager):
        """Guard editing an existing EC task's fields.

        Manager Approve and the request's Implement Owner may edit anything.
        Any other Implement Team member may additionally assign the task
        (`user_ids`) on top of Status/Evidence/etc (ASSIGNEE_EDITABLE_FIELDS)
        - the whole team decides amongst themselves who picks up which
        action, not just the Owner. Everyone else (e.g. someone assigned to
        the task but not on the Implement Team) is limited to
        ASSIGNEE_EDITABLE_FIELDS only.

        Note this only governs *which fields* may change - *which tasks* a
        given user can reach at all is a separate concern, already handled by
        the `ec_task_rule_user_write` record rule and the base ACL.
        """
        self.ensure_one()
        if self._is_ec_owner_or_manager(is_manager):
            return
        allowed_fields = self.ASSIGNEE_EDITABLE_FIELDS
        if self._is_ec_team_member():
            allowed_fields = allowed_fields | {'user_ids'}
        if set(vals) <= allowed_fields:
            return
        raise AccessError(_(
            "Only the Manager, the request's Implement Owner, or (for "
            "assigning the task) another Implement Team member can edit "
            "task details."))

    # ------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        is_manager = self._is_ec_manager()
        Change = self.env['engineering.change']
        for vals in vals_list:
            change_id = vals.get('change_id')
            if change_id:
                change = Change.browse(change_id)
                self._check_ec_create_access(change, is_manager=is_manager)
                if not vals.get('project_id'):
                    vals['project_id'] = self._get_or_create_ec_project(change).id
        tasks = super().create(vals_list)
        ec_tasks = tasks.filtered('change_id')
        ec_tasks._post_creation_message()
        for task in ec_tasks.filtered('user_ids'):
            task._post_assignment_message(task.user_ids)
        return tasks

    def unlink(self):
        is_manager = self._is_ec_manager()
        for task in self.filtered('change_id'):
            task._check_ec_delete_access(task.change_id, is_manager=is_manager)
        return super().unlink()

    def write(self, vals):
        ec_tasks = self.filtered('change_id')
        is_manager = self._is_ec_manager()
        for task in ec_tasks:
            task._check_ec_write_access(vals, is_manager)

        tasks_being_completed = self.browse()
        if vals.get('state') == '1_done':
            tasks_being_completed = ec_tasks.filtered(lambda task: task.state != '1_done')
        old_user_ids = {task.id: task.user_ids for task in ec_tasks} if 'user_ids' in vals else {}

        result = super().write(vals)

        tasks_being_completed._post_completion_message()
        if 'user_ids' in vals:
            for task in ec_tasks:
                new_users = task.user_ids - old_user_ids.get(task.id, self.env['res.users'])
                if new_users:
                    task._post_assignment_message(new_users)
        return result

    # ------------------------------------------------------------
    # Chatter messaging
    # ------------------------------------------------------------
    def _post_creation_message(self):
        """Log a new action/task on its parent request's chatter, so anyone
        watching the request sees it show up even without opening the task.

        sudo(): the Implement Team member allowed to create this task (see
        `_check_ec_create_access`) is not necessarily an Engineer/BOC/Manager
        Approve holder with write access of their own on engineering.change.
        """
        for task in self:
            task.change_id.sudo().message_post(
                body=_("New action '%s' created by %s.") % (task.name, self.env.user.name))

    def _post_assignment_message(self, new_users):
        """Notify everyone relevant to this action about a new assignment -
        the request's Implement Owner and this task's own Manager (if
        different from whoever just did the assigning), plus the newly
        assigned user(s) themselves. Separate from jacon_core's generic
        "notify the assignee's direct HR manager" hook (project_task.py's
        write()), which fires for every project.task regardless of
        change_id - this one is EC-specific, about keeping the request's
        own stakeholders in the loop, not the assignee's line management.

        sudo(): whoever is allowed to assign (see _check_ec_write_access -
        could be a plain Implement Team member) isn't necessarily an
        Engineer/BOC/Manager Approve holder with message_post access of
        their own on this task/its request.
        """
        self.ensure_one()
        owner = self.change_id.implement_owner_id
        stakeholders = new_users | owner | self.manager_id
        stakeholders = stakeholders - self.env.user
        if not stakeholders:
            return
        partners = stakeholders.mapped('partner_id')
        self.sudo().message_post(
            body=_("%(user)s assigned this action to %(assignees)s.") % {
                'user': self.env.user.name, 'assignees': ', '.join(new_users.mapped('name')),
            },
            partner_ids=partners.ids)
        self.change_id.sudo().message_post(
            body=_("%(user)s assigned action '%(task)s' to %(assignees)s.") % {
                'user': self.env.user.name, 'task': self.name,
                'assignees': ', '.join(new_users.mapped('name')),
            },
            partner_ids=partners.ids)

    def _post_completion_message(self):
        """Notify each task's parent request that the task was completed.

        sudo(): this is a system side-effect that must always succeed, even
        for an assignee with no write access of their own on engineering.change.
        """
        for task in self:
            task.change_id.sudo().message_post(
                body=_("Action '%s' completed by %s.") % (task.name, self.env.user.name))

    # ------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------
    def action_open_ec_task_form(self):
        """Open this task's own EC-specific form (with the Evidence tab and
        chatter) as a dialog, for use as an "Open" button on rows of the
        Actions tab's embedded task list - that list is editable="bottom",
        so clicking a row otherwise just starts inline editing instead of
        opening the full form.
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'project.task',
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(self.env.ref('engineering_change.view_engineering_change_action_form').id, 'form')],
            'target': 'new',
        }

    # ------------------------------------------------------------
    # Overdue reminders
    # ------------------------------------------------------------
    def _send_overdue_reminder(self):
        self.ensure_one()
        partners = (self.user_ids | self.manager_id).mapped('partner_id')
        template = self.env.ref('engineering_change.mail_template_overdue', raise_if_not_found=False)
        if template:
            template.send_mail(self.id, force_send=False, email_values={'recipient_ids': [(6, 0, partners.ids)]})
        self.message_post(
            body=_("Action '%s' is overdue.") % self.name, partner_ids=partners.ids)

    @api.model
    def _cron_check_overdue(self):
        today = fields.Date.context_today(self)
        overdue_tasks = self.search([
            ('change_id', '!=', False),
            ('date_deadline', '<', today),
            ('state', 'not in', list(DONE_STATES)),
        ])
        stale = overdue_tasks.filtered(lambda t: not t.is_overdue)
        if stale:
            stale.write({'is_overdue': True})
        no_longer_overdue = self.search([('change_id', '!=', False), ('is_overdue', '=', True)]).filtered(
            lambda t: not (t.date_deadline and fields.Date.to_date(t.date_deadline) < today
                           and t.state not in DONE_STATES)
        )
        if no_longer_overdue:
            no_longer_overdue.write({'is_overdue': False})
        for task in overdue_tasks:
            task._send_overdue_reminder()
