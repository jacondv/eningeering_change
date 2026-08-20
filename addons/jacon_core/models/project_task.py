from datetime import datetime

from odoo import _, api, fields, models
from odoo.exceptions import AccessError

from .hr_employee import _priority_value

TASK_TYPE_SELECTION = [
    ('3d', '3D'),
    ('2d', '2D'),
    ('sch', 'Sch'),
    ('bom', 'BOM'),
    ('checklist', 'Checklist'),
    ('doc', 'Doc'),
    ('fem', 'FEM'),
    ('rnd', 'R&D'),
    ('train', 'Train'),
    ('prog', 'Prog'),
    ('hyd', 'Hyd'),
    ('mnf', 'M&F'),
    ('cal', 'Cal'),
    ('test', 'Test'),
    ('s_manual', 'S-Manual'),
    ('m_manual', 'M-Manual'),
    ('o_manual', 'O-Manual'),
]


class ProjectTask(models.Model):
    _inherit = 'project.task'

    # Default to the creating user - core only does this when created from
    # a "My Tasks" personal-stage context, not from a Project's Tasks list.
    user_ids = fields.Many2many(default=lambda self: self.env.user.ids)

    task_type = fields.Selection(
        TASK_TYPE_SELECTION, string='Task Type', index=True, tracking=True)

    evidence_ids = fields.One2many(
        'engineering.change.action.evidence', 'task_id', string='Evidence')
    evidence_count = fields.Integer(compute='_compute_evidence_count')

    # Defaults to today (creation date) but is editable - e.g. push it out
    # if the task can't realistically start right away. Drives the
    # overload calculation below: remaining_hours (allocated minus already
    # logged) is scheduled across working days from here to date_deadline,
    # a fixed window rather than always "today", so the answer for a given
    # task doesn't shift depending on which day you happen to check it.
    date_start = fields.Date(string='Start Date', default=lambda self: fields.Date.context_today(self))

    # Never persisted - recomputed every time the form loads/reloads (not
    # just while editing), so it reflects the real, current state of every
    # other task in the system - e.g. it only clears after the overload
    # wizard's Save actually resolves the conflict, not just because the
    # wizard closed. See hr.employee.get_daily_load.
    overload_warning = fields.Text(
        string='Overload Warning', compute='_compute_overload_warning', store=False)

    # Never persisted, same reasoning as overload_warning above - a
    # separate check from it, though: overload_warning flags a day in
    # [date_start, date_deadline] that's paying down UNRELATED overdue
    # debt (see hr.employee._simulate_schedule), which says nothing
    # about whether THIS task's own hours actually fit in that window.
    # This one answers that directly via check_task_overload, so a brand
    # new task gets a concrete "here's a start date that works" instead
    # of only a vague "somewhere in here is tight" warning.
    suggested_start_notice = fields.Text(
        string='Suggested Start Date', compute='_compute_suggested_start', store=False)
    suggested_date_start = fields.Date(compute='_compute_suggested_start', store=False)
    suggested_date_deadline = fields.Datetime(compute='_compute_suggested_start', store=False)

    # Schedule-change self-service: an assignee proposes a new Start Date,
    # Deadline and/or Allocated Hours (via the wizard below) instead of
    # editing them directly - see SCHEDULE_FIELDS/write() below, which
    # blocks a plain assignee from touching those 3 fields any other way.
    # Their direct HR manager Approves/Rejects it. Only one pending
    # proposal at a time - a new one overwrites the old rather than
    # queuing, and these fields are cleared back to blank the moment it's
    # resolved either way (the decision itself is only kept in the
    # chatter, same as everywhere else on this model).
    proposed_date_start = fields.Date(string='Proposed Start Date', copy=False)
    proposed_date_deadline = fields.Datetime(string='Proposed Deadline', copy=False)
    proposed_allocated_hours = fields.Float(string='Proposed Allocated Hours', copy=False)
    proposed_schedule_reason = fields.Text(string='Reason for Change', copy=False)
    schedule_change_requested_by = fields.Many2one(
        'res.users', string='Requested By', copy=False, readonly=True)

    can_propose_schedule_change = fields.Boolean(compute='_compute_schedule_change_rights')
    can_approve_schedule_change = fields.Boolean(compute='_compute_schedule_change_rights')

    # Fields a plain assignee may never write directly (see write() below) -
    # only through Propose Schedule Change + their manager's Approve.
    SCHEDULE_FIELDS = frozenset({'date_start', 'date_deadline', 'allocated_hours'})

    @api.depends('evidence_ids')
    def _compute_evidence_count(self):
        for rec in self:
            rec.evidence_count = len(rec.evidence_ids)

    @api.model
    def search_task_title_suggestions(self, query, limit=8):
        """Distinct, previously-used Task titles containing `query`, each
        paired with the Task Type of their most recent use - powers the
        autocomplete dropdown on the Title field (see
        task_title_autocomplete_field.js) so a user typing a few characters
        can reuse a title they (or anyone else) already used before, with
        its Task Type filled in too, instead of retyping both slightly
        differently every time. Plain search(), not read_group/SQL, so it
        still respects the normal project.task record rules (a user only
        gets suggested titles from tasks they can actually see). Ordered
        most-recently-updated first, so of several tasks sharing a title,
        the Task Type offered is the one most recently actually used under
        it."""
        if not query or len(query) < 2:
            return []
        tasks = self.search([('name', 'ilike', query)], order='write_date desc', limit=200)
        seen = set()
        suggestions = []
        for task in tasks:
            if not task.name or task.name in seen:
                continue
            seen.add(task.name)
            suggestions.append({'name': task.name, 'task_type': task.task_type})
            if len(suggestions) >= limit:
                break
        return suggestions

    def _get_assigned_employees(self):
        return self.env['hr.employee'].search([('user_id', 'in', self.user_ids.ids)])

    def _get_deadline_change_managers(self):
        """Direct HR manager(s) (hr.employee.parent_id.user_id) of every
        employee currently assigned to this task - whoever may Approve/
        Reject a pending schedule-change proposal, and who's exempt from
        the SCHEDULE_FIELDS write-lock below (see _is_schedule_change_exempt).
        Same "direct manager" pattern as engineering.change's Line Manager
        approval: the real approver is whoever manages the person actually
        doing the work, not a fixed role, and a task can have several
        assignees so this can resolve to more than one manager."""
        self.ensure_one()
        return self._get_assigned_employees().mapped('parent_id.user_id')

    def _is_schedule_change_exempt(self):
        """Whoever may write Start Date/Deadline/Allocated Hours directly,
        without going through Propose Schedule Change + Approve - Project
        Manager, Admin, or the assignee's own direct manager (who could
        just approve a proposal anyway, so skipping that round trip
        changes nothing)."""
        self.ensure_one()
        user = self.env.user
        if user.has_group('base.group_system') or user.has_group('project.group_project_manager'):
            return True
        return user in self._get_deadline_change_managers()

    @api.depends('user_ids', 'proposed_date_start', 'proposed_date_deadline', 'proposed_allocated_hours')
    def _compute_schedule_change_rights(self):
        user = self.env.user
        is_admin = user.has_group('base.group_system')
        for task in self:
            has_proposal = bool(
                task.proposed_date_start or task.proposed_date_deadline or task.proposed_allocated_hours)
            task.can_propose_schedule_change = bool(user in task.user_ids and not has_proposal)
            task.can_approve_schedule_change = bool(
                has_proposal and (is_admin or user in task._get_deadline_change_managers()))

    def _check_can_approve_schedule_change(self):
        self.ensure_one()
        user = self.env.user
        if user.has_group('base.group_system'):
            return
        if user not in self._get_deadline_change_managers():
            raise AccessError(_(
                "Only this task assignee's direct manager can approve or reject a schedule change."))

    def action_propose_schedule_change(self):
        self.ensure_one()
        if self.env.user not in self.user_ids:
            raise AccessError(_("Only an assignee of this task can propose a schedule change."))
        return {
            'type': 'ir.actions.act_window',
            'name': 'Propose Schedule Change',
            'res_model': 'jacon.task.propose.schedule.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_task_id': self.id,
                'default_new_date_start': self.date_start,
                'default_new_date_deadline': self.date_deadline,
                'default_new_allocated_hours': self.allocated_hours,
            },
        }

    def action_approve_schedule_change(self):
        for task in self:
            task._check_can_approve_schedule_change()
            changes = []
            vals = {
                'proposed_date_start': False,
                'proposed_date_deadline': False,
                'proposed_allocated_hours': False,
                'proposed_schedule_reason': False,
                'schedule_change_requested_by': False,
            }
            if task.proposed_date_start and task.proposed_date_start != task.date_start:
                changes.append(_('Start Date: %(old)s → %(new)s') % {
                    'old': task.date_start, 'new': task.proposed_date_start})
                vals['date_start'] = task.proposed_date_start
            if task.proposed_date_deadline and task.proposed_date_deadline != task.date_deadline:
                changes.append(_('Deadline: %(old)s → %(new)s') % {
                    'old': task.date_deadline, 'new': task.proposed_date_deadline})
                vals['date_deadline'] = task.proposed_date_deadline
            if task.proposed_allocated_hours and task.proposed_allocated_hours != task.allocated_hours:
                changes.append(_('Allocated Hours: %(old)s → %(new)s') % {
                    'old': task.allocated_hours, 'new': task.proposed_allocated_hours})
                vals['allocated_hours'] = task.proposed_allocated_hours
            task.with_context(schedule_write_allowed=True).write(vals)
            task.message_post(body=_(
                "Schedule change approved by %(user)s: %(changes)s.") % {
                    'user': self.env.user.name, 'changes': '; '.join(changes) or _('no change'),
                })

    def action_reject_schedule_change(self):
        for task in self:
            task._check_can_approve_schedule_change()
            requester = task.schedule_change_requested_by
            task.write({
                'proposed_date_start': False,
                'proposed_date_deadline': False,
                'proposed_allocated_hours': False,
                'proposed_schedule_reason': False,
                'schedule_change_requested_by': False,
            })
            task.message_post(
                body=_("Schedule change request rejected by %s.") % self.env.user.name,
                partner_ids=requester.partner_id.ids if requester else [])

    @api.model_create_multi
    def create(self, vals_list):
        tasks = super().create(vals_list)
        for task in tasks:
            if task.user_ids:
                task._notify_managers_of_assignment(task.user_ids)
        return tasks

    def write(self, vals):
        schedule_keys = set(vals) & self.SCHEDULE_FIELDS
        if schedule_keys and not self.env.context.get('schedule_write_allowed'):
            for task in self:
                if not task._is_schedule_change_exempt():
                    raise AccessError(_(
                        "%s can only be changed via 'Propose Schedule Change', approved by your manager."
                    ) % ', '.join(sorted(schedule_keys)))
        old_user_ids = {task.id: task.user_ids for task in self} if 'user_ids' in vals else {}
        result = super().write(vals)
        if 'user_ids' in vals:
            for task in self:
                new_users = task.user_ids - old_user_ids.get(task.id, self.env['res.users'])
                if new_users:
                    task._notify_managers_of_assignment(new_users)
        return result

    def _notify_managers_of_assignment(self, new_users):
        """Notify each newly-assigned employee's direct HR manager
        (Employee > Manager) that their report was just put on this task -
        so the manager finds out from the task itself instead of only
        noticing when a schedule-change proposal later needs their
        approval."""
        self.ensure_one()
        employees = self.env['hr.employee'].search([('user_id', 'in', new_users.ids)])
        for employee in employees:
            manager_user = employee.parent_id.user_id
            if not manager_user or manager_user == employee.user_id:
                continue
            self.message_subscribe(partner_ids=manager_user.partner_id.ids)
            self.message_post(
                body=_("%(employee)s was assigned to this task.") % {'employee': employee.name},
                partner_ids=manager_user.partner_id.ids)

    def _suggest_or_keep_deadline(self):
        """Nearest deadline this task's assignee has room for, or the
        task's current deadline if none was found within the search
        horizon - used to pre-fill the overload wizard's "New Deadline"
        column so it already opens on a sensible date instead of the one
        causing the overload."""
        self.ensure_one()
        employee = self._get_assigned_employees()[:1]
        remaining = max(self.remaining_hours or 0.0, 0.0)
        if employee and remaining:
            suggested = employee.suggest_deadline_without_overload(
                remaining, self.date_start, after_date=self.date_deadline, exclude_task_id=self.id,
                priority=_priority_value(self.priority))
            if suggested:
                time_of_day = (self.date_deadline or fields.Datetime.now()).time()
                return datetime.combine(suggested, time_of_day)
        return self.date_deadline

    def _get_overloaded_ranges(self):
        """(employee, day-range) pairs where this task's assignee(s) would
        be over daily capacity somewhere between this task's start and
        deadline, counting this task's own remaining hours (allocated
        minus already logged, see remaining_hours) on top of their other
        open tasks - day-level debt, used by action_view_overload_conflicts
        to list which other tasks are contributing to that debt. NOT used
        by the warning banner (see _compute_overload_warning) - a day can
        be in debt purely from a *different*, unrelated overdue task, which
        this task's own deadline doesn't cause and moving it wouldn't fix."""
        self.ensure_one()
        remaining = max(self.remaining_hours or 0.0, 0.0)
        if not (self.user_ids and remaining and self.date_deadline):
            return []
        start = self.date_start or fields.Date.context_today(self)
        exclude_id = self._origin.id or None
        result = []
        for employee in self._get_assigned_employees():
            ranges = employee.get_overloaded_ranges(
                start, self.date_deadline,
                extra_remaining=[(remaining, start, self.date_deadline, _priority_value(self.priority))],
                exclude_task_id=exclude_id)
            result += [(employee, rng) for rng in ranges]
        return result

    @api.depends('user_ids', 'remaining_hours', 'date_start', 'date_deadline', 'priority')
    def _compute_overload_warning(self):
        """Task-level: would THIS task's own remaining hours fail to
        finish by its own deadline once queued by priority alongside the
        assignee's other open tasks - the same definition Task Timeline
        uses to flag a bar as overloaded (hr.employee.get_task_overload)
        and suggested_start_notice below already uses, so the banner never
        disagrees with either of those for the same task. Deliberately NOT
        day-level debt (see _get_overloaded_ranges) - that can fire from a
        colleague's unrelated overdue task and confusingly implicate this
        one instead."""
        for task in self:
            remaining = max(task.remaining_hours or 0.0, 0.0)
            if not (task.user_ids and remaining and task.date_deadline):
                task.overload_warning = False
                continue
            start = task.date_start or fields.Date.context_today(task)
            deadline = fields.Date.to_date(task.date_deadline)
            if start > deadline:
                start = deadline
            exclude_id = task._origin.id or None
            priority = _priority_value(task.priority)
            lines = []
            for employee in task._get_assigned_employees():
                _days, _task_results, extra_results = employee._simulate_schedule(
                    start, deadline,
                    extra_remaining=[(remaining, start, deadline, priority)],
                    exclude_task_id=exclude_id)
                if extra_results and extra_results[0]['overloaded']:
                    lines.append('%s: %.1fh of this task would not be finished by %s' % (
                        employee.name, extra_results[0]['unfinished_hours'],
                        deadline.strftime('%d-%m-%Y')))
            task.overload_warning = '\n'.join(lines) if lines else False

    @api.depends('user_ids', 'remaining_hours', 'date_start', 'date_deadline', 'priority')
    def _compute_suggested_start(self):
        for task in self:
            task.suggested_start_notice = False
            task.suggested_date_start = False
            task.suggested_date_deadline = False
            remaining = max(task.remaining_hours or 0.0, 0.0)
            if not (task.user_ids and remaining and task.date_deadline):
                continue
            employee = task._get_assigned_employees()[:1]
            if not employee:
                continue
            start = task.date_start or fields.Date.context_today(task)
            deadline = fields.Date.to_date(task.date_deadline)
            if start > deadline:
                start = deadline
            exclude_id = task._origin.id or None
            priority = _priority_value(task.priority)
            base_queue = employee._task_queue()
            if not employee.check_task_overload(
                    remaining, start, deadline, priority=priority, exclude_task_id=exclude_id,
                    base_queue=base_queue):
                continue
            weekdays = employee._work_weekdays()
            duration_work_days = employee._count_work_days(start, deadline, weekdays) or 1
            suggestion = employee.suggest_start_without_overload(
                remaining, duration_work_days, priority=priority,
                after_date=start, exclude_task_id=exclude_id, base_queue=base_queue)
            if not suggestion:
                continue
            new_start, new_deadline = suggestion
            task.suggested_date_start = new_start
            time_of_day = (task.date_deadline or fields.Datetime.now()).time()
            task.suggested_date_deadline = datetime.combine(new_deadline, time_of_day)
            task.suggested_start_notice = (
                'Starting %s would overload %s - they wouldn\'t finish this task in time. '
                'Suggested: %s → %s (same length, next slot with room).' % (
                    start.strftime('%d-%m-%Y'), employee.name,
                    new_start.strftime('%d-%m'), new_deadline.strftime('%d-%m-%Y')))

    def action_apply_suggested_start(self):
        for task in self:
            if task.suggested_date_start and task.suggested_date_deadline:
                task.with_context(schedule_write_allowed=True).write({
                    'date_start': task.suggested_date_start,
                    'date_deadline': task.suggested_date_deadline,
                })

    def action_view_overload_conflicts(self):
        """Open a review wizard (not a direct edit) for the other open
        tasks contributing to this task's overload - deadlines are only
        applied to the real tasks if the user clicks Save on the wizard."""
        self.ensure_one()
        task_ids = set()
        for _employee, rng in self._get_overloaded_ranges():
            task_ids.update(rng['task_ids'])
        conflicts = self.env['project.task'].browse(task_ids)
        wizard = self.env['jacon.task.deadline.wizard'].create({
            'line_ids': [
                (0, 0, {'task_id': task.id, 'new_deadline': task._suggest_or_keep_deadline()})
                for task in conflicts
            ],
        })
        return {
            'type': 'ir.actions.act_window',
            'name': 'Tasks in Schedule Conflict',
            'res_model': 'jacon.task.deadline.wizard',
            'view_mode': 'form',
            'res_id': wizard.id,
            'target': 'new',
        }
