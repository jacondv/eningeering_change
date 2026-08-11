from odoo import fields, models


class TaskDeadlineWizard(models.TransientModel):
    """Review screen opened from a Task's overload warning: proposed new
    deadlines only touch this wizard's own (transient) storage until
    `action_apply` is clicked - nothing is written to the real tasks
    before that, so a manager can freely try suggestions and back out."""
    _name = 'jacon.task.deadline.wizard'
    _description = 'Resolve Overloaded Tasks'

    line_ids = fields.One2many('jacon.task.deadline.wizard.line', 'wizard_id', string='Tasks')

    def action_apply(self):
        for line in self.line_ids:
            if line.new_deadline and line.new_deadline != line.task_id.date_deadline:
                line.task_id.date_deadline = line.new_deadline
        return {'type': 'ir.actions.act_window_close'}


class TaskDeadlineWizardLine(models.TransientModel):
    _name = 'jacon.task.deadline.wizard.line'
    _description = 'Resolve Overloaded Tasks - Line'

    wizard_id = fields.Many2one('jacon.task.deadline.wizard', required=True, ondelete='cascade')
    task_id = fields.Many2one('project.task', required=True, readonly=True)
    project_id = fields.Many2one(related='task_id.project_id', readonly=True)
    user_ids = fields.Many2many(related='task_id.user_ids', readonly=True)
    remaining_hours = fields.Float(related='task_id.remaining_hours', readonly=True)
    current_deadline = fields.Datetime(related='task_id.date_deadline', readonly=True, string='Current Deadline')
    # Pre-filled by the caller when creating the line (see
    # project.task._suggest_or_keep_deadline / action_view_overload_conflicts)
    # with the nearest week the assignee has room, so the field already
    # opens on a sensible date - the user can still pick any other date
    # normally, it's just a starting point, not applied until Save.
    new_deadline = fields.Datetime(string='New Deadline', required=True)
