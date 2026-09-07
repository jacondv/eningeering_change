from odoo import fields, models


class ProjectTaskDescriptionLog(models.Model):
    """One immutable row per edit to any Task's Description - who changed
    it, when, and a line-level diff (added/removed lines only, plain text) -
    kept as evidence, separate from the task's own Chatter (which already
    carries assignment/stage-change/schedule-approval messages and would
    just add noise here). See ProjectTask._log_description_change, which is
    the only place that ever creates these rows.
    """
    _name = 'project.task.description.log'
    _description = 'Task Description Change Log'
    _order = 'date desc, id desc'

    task_id = fields.Many2one('project.task', required=True, ondelete='cascade', index=True)
    user_id = fields.Many2one('res.users', required=True, default=lambda self: self.env.user)
    date = fields.Datetime(required=True, default=fields.Datetime.now)
    diff = fields.Text(required=True)
