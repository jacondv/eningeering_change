from odoo import _, fields, models


class TaskProposeScheduleWizard(models.TransientModel):
    """Opened from a Task's "Propose Schedule Change" button (assignee only -
    see project.task.action_propose_schedule_change). Writes the proposal
    onto the task's own proposed_* fields and notifies the assignee's
    direct manager(s) - nothing changes on the real Start Date/Deadline/
    Allocated Hours until that manager Approves it from the task form."""
    _name = 'jacon.task.propose.schedule.wizard'
    _description = 'Propose Task Schedule Change'

    task_id = fields.Many2one('project.task', required=True)
    current_date_start = fields.Date(related='task_id.date_start', readonly=True)
    current_date_deadline = fields.Datetime(related='task_id.date_deadline', readonly=True)
    current_allocated_hours = fields.Float(related='task_id.allocated_hours', readonly=True)
    new_date_start = fields.Date(string='New Start Date', required=True)
    new_date_deadline = fields.Datetime(string='New Deadline', required=True)
    new_allocated_hours = fields.Float(string='New Allocated Hours', required=True)
    reason = fields.Text(string='Reason', required=True)

    def action_submit(self):
        self.ensure_one()
        task = self.task_id
        changes = []
        vals = {'proposed_schedule_reason': self.reason, 'schedule_change_requested_by': self.env.user.id}
        if self.new_date_start != task.date_start:
            changes.append(_('Start Date: %(old)s → %(new)s') % {
                'old': task.date_start, 'new': self.new_date_start})
            vals['proposed_date_start'] = self.new_date_start
        if self.new_date_deadline != task.date_deadline:
            changes.append(_('Deadline: %(old)s → %(new)s') % {
                'old': task.date_deadline, 'new': self.new_date_deadline})
            vals['proposed_date_deadline'] = self.new_date_deadline
        if self.new_allocated_hours != task.allocated_hours:
            changes.append(_('Allocated Hours: %(old)s → %(new)s') % {
                'old': task.allocated_hours, 'new': self.new_allocated_hours})
            vals['proposed_allocated_hours'] = self.new_allocated_hours
        task.write(vals)
        managers = task._get_deadline_change_managers()
        task.message_post(
            body=_(
                "%(user)s proposed a schedule change: %(changes)s.\nReason: %(reason)s"
            ) % {
                'user': self.env.user.name,
                'changes': '; '.join(changes) or _('no change'),
                'reason': self.reason,
            },
            partner_ids=managers.mapped('partner_id').ids)
        return {'type': 'ir.actions.act_window_close'}
