from odoo import _, fields, models


class TaskProposeDeadlineWizard(models.TransientModel):
    """Opened from a Task's "Propose New Deadline" button (assignee only -
    see project.task.action_propose_deadline_change). Writes the proposal
    onto the task's own proposed_* fields and notifies the assignee's
    direct manager(s) - nothing changes on the real date_deadline until
    that manager Approves it from the task form."""
    _name = 'jacon.task.propose.deadline.wizard'
    _description = 'Propose New Task Deadline'

    task_id = fields.Many2one('project.task', required=True)
    current_deadline = fields.Datetime(related='task_id.date_deadline', readonly=True)
    new_deadline = fields.Datetime(string='New Deadline', required=True)
    reason = fields.Text(string='Reason', required=True)

    def action_submit(self):
        self.ensure_one()
        old_deadline = self.task_id.date_deadline
        self.task_id.write({
            'proposed_deadline': self.new_deadline,
            'proposed_deadline_reason': self.reason,
            'deadline_change_requested_by': self.env.user.id,
        })
        managers = self.task_id._get_deadline_change_managers()
        self.task_id.message_post(
            body=_(
                "%(user)s proposed a new deadline: %(old)s → %(new)s.\nReason: %(reason)s"
            ) % {
                'user': self.env.user.name,
                'old': old_deadline,
                'new': self.new_deadline,
                'reason': self.reason,
            },
            partner_ids=managers.mapped('partner_id').ids)
        return {'type': 'ir.actions.act_window_close'}
