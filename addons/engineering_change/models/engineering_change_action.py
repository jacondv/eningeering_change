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
    evidence_ids = fields.One2many('engineering.change.action.evidence', 'task_id', string='Evidence')
    evidence_count = fields.Integer(compute='_compute_evidence_count')
    is_overdue = fields.Boolean(compute='_compute_is_overdue', store=True)

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

    def _default_ec_manager_id(self):
        change_id = self.env.context.get('default_change_id')
        if change_id:
            change = self.env['engineering.change'].browse(change_id)
            if change.bod_approver_id:
                return change.bod_approver_id.id
        return self.env.user.id

    @api.depends('evidence_ids')
    def _compute_evidence_count(self):
        for rec in self:
            rec.evidence_count = len(rec.evidence_ids)

    @api.depends('date_deadline', 'state')
    def _compute_is_overdue(self):
        today = fields.Date.context_today(self)
        for rec in self:
            deadline = rec.date_deadline and fields.Date.to_date(rec.date_deadline)
            rec.is_overdue = bool(
                rec.change_id and deadline and deadline < today and rec.state not in DONE_STATES)

    # Fields an EC task's own assignee may touch without being Manager Approve
    # or Implement Owner. Kept as a class constant (same style as ENGINEER_FIELDS
    # / MANAGER_FIELDS on engineering.change) so the "what" is declared once and
    # reused by both the write guard and its error message.
    ASSIGNEE_EDITABLE_FIELDS = frozenset({
        'state',
        'evidence_ids',
        # written automatically by project.task's own write() as a side effect
        # of a state change - not something the user is choosing to set.
        'date_last_stage_update',
    })

    @api.model
    def _is_ec_manager(self):
        """Manager Approve holders have unrestricted access to every EC task."""
        return self.env.user.has_group('engineering_change.group_ec_manager')

    def _check_ec_manage_access(self, change, is_manager=None):
        """Guard create/delete of an EC task: only Manager Approve or `change`'s
        own Implement Owner may create or remove actions on it.

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
        if is_manager or change.implement_owner_id == self.env.user:
            return
        raise AccessError(_(
            "Only the Manager or the request's Implement Owner can create or "
            "delete actions/tasks for this request."))

    def _check_ec_write_access(self, vals, is_manager):
        """Guard editing an existing EC task's fields.

        Manager Approve and the request's Implement Owner may edit anything;
        everyone else (e.g. a plain assignee) may only touch Status/Evidence.
        Note this only governs *which fields* may change - *which tasks* a
        given user can reach at all is a separate concern, already handled by
        the `ec_task_rule_user_write` record rule and the base ACL.
        """
        self.ensure_one()
        if is_manager or set(vals) <= self.ASSIGNEE_EDITABLE_FIELDS:
            return
        if self.change_id.implement_owner_id == self.env.user:
            return
        raise AccessError(_(
            "Only the Manager or the request's Implement Owner can edit task "
            "details. You can only update the Status and Evidence."))

    @api.model_create_multi
    def create(self, vals_list):
        is_manager = self._is_ec_manager()
        Change = self.env['engineering.change']
        for vals in vals_list:
            change_id = vals.get('change_id')
            if change_id:
                self._check_ec_manage_access(Change.browse(change_id), is_manager=is_manager)
        tasks = super().create(vals_list)
        tasks.filtered('change_id')._post_creation_message()
        return tasks

    def unlink(self):
        is_manager = self._is_ec_manager()
        for task in self.filtered('change_id'):
            task._check_ec_manage_access(task.change_id, is_manager=is_manager)
        return super().unlink()

    def write(self, vals):
        ec_tasks = self.filtered('change_id')
        is_manager = self._is_ec_manager()
        for task in ec_tasks:
            task._check_ec_write_access(vals, is_manager)

        tasks_being_completed = self.browse()
        if vals.get('state') == '1_done':
            tasks_being_completed = ec_tasks.filtered(lambda task: task.state != '1_done')

        result = super().write(vals)

        tasks_being_completed._post_completion_message()
        return result

    def _post_creation_message(self):
        """Log a new action/task on its parent request's chatter, so anyone
        watching the request sees it show up even without opening the task.

        sudo(): the Implement Owner allowed to create this task (see
        `_check_ec_manage_access`) is not necessarily an Engineer/BOD/Manager
        Approve holder with write access of their own on engineering.change.
        """
        for task in self:
            task.change_id.sudo().message_post(
                body=_("New action '%s' created by %s.") % (task.name, self.env.user.name))

    def _post_completion_message(self):
        """Notify each task's parent request that the task was completed.

        sudo(): this is a system side-effect that must always succeed, even
        for an assignee with no write access of their own on engineering.change.
        """
        for task in self:
            task.change_id.sudo().message_post(
                body=_("Action '%s' completed by %s.") % (task.name, self.env.user.name))

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
