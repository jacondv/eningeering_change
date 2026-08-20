from html import escape

from odoo import fields, models

_LEVEL_COLORS = {
    'over': '#e15759',
    'tight': '#edc948',
    'busy': '#59a14f',
    'free': '#cfe8cc',
}


def _day_level(day):
    if day['overloaded']:
        return 'over'
    if day['capacity'] and day['load'] / day['capacity'] >= 0.85:
        return 'tight'
    if day['load'] > 0:
        return 'busy'
    return 'free'


class TaskDeadlineWizard(models.TransientModel):
    """Review screen opened from a Task's overload warning: proposed new
    deadlines only touch this wizard's own (transient) storage until
    `action_apply` is clicked - nothing is written to the real tasks
    before that, so a manager can freely try suggestions and back out."""
    _name = 'jacon.task.deadline.wizard'
    _description = 'Resolve Overloaded Tasks'

    line_ids = fields.One2many('jacon.task.deadline.wizard.line', 'wizard_id', string='Tasks')
    # Read-only day-by-day picture of the affected employees' real,
    # current schedule (not the proposed new_deadline edits below - those
    # aren't applied yet) so a manager can *see* which days overlap
    # instead of only reading a text warning, before picking new dates.
    gantt_html = fields.Html(compute='_compute_gantt_html', sanitize=False)

    def _compute_gantt_html(self):
        for wizard in self:
            wizard.gantt_html = wizard._build_gantt_html()

    def _build_gantt_html(self):
        self.ensure_one()
        tasks = self.line_ids.task_id
        employees = self.env['hr.employee'].search([('user_id', 'in', tasks.user_ids.ids)])
        if not tasks or not employees:
            return False

        today = fields.Date.context_today(self)
        starts = [fields.Date.to_date(t.date_start) or today for t in tasks] + [today]
        ends = [fields.Date.to_date(t.date_deadline) for t in tasks if t.date_deadline]
        ends += [fields.Date.to_date(l.new_deadline) for l in self.line_ids if l.new_deadline]
        start = max(min(starts), today)
        end = max(ends) if ends else start
        if end < start:
            end = start

        rows = []
        for emp in employees:
            days = emp.get_daily_load(start, end)
            if not days:
                continue
            cells = []
            for day in days:
                level = _day_level(day)
                title = escape('%s: %.1fh / %.1fh%s' % (
                    day['date'].strftime('%d/%m'), day['load'], day['capacity'],
                    ' (overloaded)' if day['overloaded'] else ''))
                cells.append(
                    '<td title="%s" style="width:16px;height:16px;background:%s;'
                    'border-radius:2px;"></td>' % (title, _LEVEL_COLORS[level]))
            rows.append(
                '<tr><th style="text-align:left;padding-right:8px;white-space:nowrap;'
                'font-weight:500;font-size:.85rem;">%s</th>%s</tr>' % (escape(emp.name), ''.join(cells)))
        if not rows:
            return False
        return (
            '<div style="overflow-x:auto;"><table style="border-spacing:2px;border-collapse:separate;">'
            '%s</table></div>' % ''.join(rows))

    def action_apply(self):
        for line in self.line_ids:
            if line.new_deadline and line.new_deadline != line.task_id.date_deadline:
                line.task_id.with_context(schedule_write_allowed=True).date_deadline = line.new_deadline
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
