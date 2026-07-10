from odoo import _, api, models


class EngineeringChange(models.Model):
    """Read-only navigation and reporting: methods that build an act_window
    to view related records (the Actions/Evidence stat buttons, the
    Dashboard's task links), plus the Dashboard's own data aggregation.
    Nothing here writes to the record - split out from engineering_change.py
    (fields/guards) and engineering_change_workflow.py (state machine) for
    that reason.
    """
    _inherit = 'engineering.change'

    def action_view_actions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Actions'),
            'res_model': 'project.task',
            'view_mode': 'list,form',
            'views': [
                (self.env.ref('engineering_change.view_engineering_change_action_list').id, 'list'),
                (self.env.ref('engineering_change.view_engineering_change_action_form').id, 'form'),
            ],
            'domain': [('change_id', '=', self.id)],
            'context': {'default_change_id': self.id},
        }

    def action_view_evidence(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Evidence'),
            'res_model': 'engineering.change.action.evidence',
            'view_mode': 'list,form',
            'views': [
                (self.env.ref('engineering_change.view_engineering_change_action_evidence_list').id, 'list'),
                (self.env.ref('engineering_change.view_engineering_change_action_evidence_form').id, 'form'),
            ],
            'domain': [('task_id.change_id', '=', self.id)],
        }

    # ------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------
    @api.model
    def get_dashboard_data(self):
        """Aggregate stats for the Dashboard client action. Uses search_read +
        Python aggregation (instead of read_group) since dataset sizes here are
        small and it sidesteps any read_group API differences in this build.
        Respects ir.rule like any other read, so every role sees the same
        totals (matches the "everyone can view everything" design).
        """
        Change = self.env['engineering.change']
        Task = self.env['project.task']

        changes = Change.search_read(
            [], ['state', 'request_type', 'rpn_level', 'has_overdue_action'])
        state_selection = Change._fields['state'].selection
        type_selection = Change._fields['request_type'].selection
        rpn_selection = Change._fields['rpn_level'].selection

        state_counts = {key: 0 for key, _label in state_selection}
        type_counts = {key: 0 for key, _label in type_selection}
        rpn_counts = {key: 0 for key, _label in rpn_selection}
        overdue_requests = 0
        for c in changes:
            state_counts[c['state']] = state_counts.get(c['state'], 0) + 1
            type_counts[c['request_type']] = type_counts.get(c['request_type'], 0) + 1
            if c['rpn_level']:
                rpn_counts[c['rpn_level']] = rpn_counts.get(c['rpn_level'], 0) + 1
            if c['has_overdue_action']:
                overdue_requests += 1

        tasks = Task.search_read([('change_id', '!=', False)], ['state', 'is_overdue'])
        task_state_selection = Task._fields['state'].selection
        task_state_counts = {key: 0 for key, _label in task_state_selection}
        overdue_tasks = 0
        done_tasks = 0
        for t in tasks:
            task_state_counts[t['state']] = task_state_counts.get(t['state'], 0) + 1
            if t['is_overdue']:
                overdue_tasks += 1
            if t['state'] == '1_done':
                done_tasks += 1
        total_tasks = len(tasks)
        task_progress = round(done_tasks / total_tasks * 100, 1) if total_tasks else 0.0

        recent_requests = Change.search_read(
            [], ['name', 'title', 'state', 'request_type', 'engineer_id'],
            order='create_date desc', limit=8)

        my_open_tasks = Task.search_read(
            [
                ('change_id', '!=', False),
                ('user_ids', 'in', [self.env.user.id]),
                ('state', 'not in', ['1_done', '1_canceled']),
            ],
            ['name', 'change_id', 'date_deadline', 'is_overdue'],
            order='date_deadline asc', limit=8)

        return {
            'total_requests': len(changes),
            'state_counts': [
                {'key': k, 'label': label, 'count': state_counts.get(k, 0)}
                for k, label in state_selection
            ],
            'type_counts': [
                {'key': k, 'label': label, 'count': type_counts.get(k, 0)}
                for k, label in type_selection
            ],
            'rpn_counts': [
                {'key': k, 'label': label, 'count': rpn_counts.get(k, 0)}
                for k, label in rpn_selection
            ],
            'overdue_requests': overdue_requests,
            'total_tasks': total_tasks,
            'done_tasks': done_tasks,
            'overdue_tasks': overdue_tasks,
            'task_progress': task_progress,
            'task_state_counts': [
                {'key': k, 'label': label, 'count': task_state_counts.get(k, 0)}
                for k, label in task_state_selection
            ],
            'recent_requests': recent_requests,
            'my_open_tasks': my_open_tasks,
        }

    @api.model
    def get_ec_task_action(self, domain=None, res_id=None):
        """Build an act_window action on project.task using this addon's own
        Task list/form views (same ones the Actions/Tasks menu uses) rather
        than core Project's default views. Used by the Dashboard client
        action so its links open the same views/columns a user would get by
        clicking through the actual menu, without depending on the search
        view's default filters (which shouldn't apply to a dashboard link
        that's already about one specific status/record).
        """
        action = {
            'type': 'ir.actions.act_window',
            'name': _('Actions / Tasks'),
            'res_model': 'project.task',
            'views': [
                (self.env.ref('engineering_change.view_engineering_change_action_list').id, 'list'),
                (self.env.ref('engineering_change.view_engineering_change_action_form').id, 'form'),
            ],
            'domain': domain or [('change_id', '!=', False)],
        }
        if res_id:
            action['res_id'] = res_id
            action['view_mode'] = 'form'
        return action
