from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError


class EngineeringChangeActionCheck(models.Model):
    """One line of an action's "Impact Checklist": one Impacted Model or one Impacted Job Number of the
    action, done (or found not to need a change) on its own.

    An action such as "Update 3D" may have to be done on many models and jobs; the lines let each of them be
    ticked separately, and the action itself can only be marked Done once none is left to do. The lines are
    made and removed by ProjectTask._sync_ec_checks when the action's Impacted Models / Job Numbers change:
    users only choose a status and a note.
    """
    _name = 'engineering.change.action.check'
    _description = 'Engineering Change Action Impact Check'
    _order = 'task_id, sequence, id'

    task_id = fields.Many2one('project.task', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    model_id = fields.Many2one('equipment.model', string='Model', ondelete='cascade')
    project_id = fields.Many2one('project.project', string='Job Number', ondelete='cascade')
    kind = fields.Selection([('model', 'Model'), ('job', 'Job Number')], compute='_compute_kind')
    item_name = fields.Char(string='Model / Job', compute='_compute_item_name')
    status = fields.Selection([
        ('todo', 'To do'),
        ('done', 'Done'),
        ('no_change', 'No change'),
    ], default='todo', required=True, index=True,
        help="Done: the work was done for this model / job. No change: it was looked at and needs nothing.")
    done_by_id = fields.Many2one('res.users', string='By', readonly=True)
    done_date = fields.Datetime(string='On', readonly=True)
    note = fields.Char()
    can_edit = fields.Boolean(compute='_compute_can_edit')

    _model_unique = models.Constraint(
        'UNIQUE(task_id, model_id)', "A model is listed only once in an action's checklist.")
    _project_unique = models.Constraint(
        'UNIQUE(task_id, project_id)', "A job is listed only once in an action's checklist.")
    _one_item = models.Constraint(
        'CHECK((model_id IS NULL) != (project_id IS NULL))', "A line is for one model or for one job.")

    @api.depends('model_id', 'project_id')
    def _compute_kind(self):
        for rec in self:
            rec.kind = 'model' if rec.model_id else 'job'

    @api.depends('model_id', 'project_id')
    def _compute_item_name(self):
        for rec in self:
            rec.item_name = (rec.model_id or rec.project_id).display_name or ''

    @api.depends_context('uid')
    @api.depends('task_id.user_ids', 'task_id.change_id.implement_owner_id')
    def _compute_can_edit(self):
        """Who may set the status: whoever may carry out the action - its assignees, the request's
        Implement Owner and Manager Approve (the record rules say the same)."""
        user = self.env.user
        is_manager = self.env.su or user.has_group('engineering_change.group_ec_manager')
        for rec in self:
            task = rec.task_id
            rec.can_edit = bool(
                is_manager or user in task.user_ids or task.change_id.implement_owner_id == user)

    # ------------------------------------------------------------
    # Who did it, and when
    # ------------------------------------------------------------
    def _status_stamp(self, status):
        """What is written next to a status: who and when for Done / No change, nothing for To do."""
        if status == 'todo':
            return {'done_by_id': False, 'done_date': False}
        return {'done_by_id': self.env.user.id, 'done_date': fields.Datetime.now()}

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('status', 'todo') != 'todo':
                for key, value in self._status_stamp(vals['status']).items():
                    vals.setdefault(key, value)
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su and set(vals) - {'status', 'note'}:
            # Lines are made and removed by the action; a user only answers them.
            raise AccessError(_("Only the status and the note of a checklist line can be changed."))
        if 'status' not in vals:
            return super().write(vals)
        # Who and when are written only for the lines whose status really changes.
        changed = self.filtered(lambda rec: rec.status != vals['status'])
        unchanged = self - changed
        if unchanged:
            super(EngineeringChangeActionCheck, unchanged).write(vals)
        if changed:
            super(EngineeringChangeActionCheck, changed).write({**vals, **self._status_stamp(vals['status'])})
            changed._post_status_messages()
        return True

    def action_set_status(self, status):
        """Set the status of the picked lines in one go (the bar of the Impact Checklist). Lines the user may
        not change are left as they are, and counted; if none can be changed it is refused."""
        if status not in dict(self._fields['status'].selection):
            raise UserError(_("Unknown status."))
        editable = self.filtered('can_edit')
        if self and not editable:
            raise AccessError(_("You may not change these lines: only the action's assignees, the request's "
                                "Implement Owner and Manager Approve can."))
        editable.write({'status': status})
        return {'done': len(editable), 'skipped': len(self) - len(editable)}

    def _post_status_messages(self):
        """Log the answers on the request's chatter, so anyone following the request sees them: one message
        for each action and status, however many lines were set at once.

        sudo(): whoever may answer a line is not necessarily allowed to post on the request."""
        labels = dict(self._fields['status']._description_selection(self.env))
        for task in self.task_id:
            for status in dict.fromkeys(self.filtered(lambda rec: rec.task_id == task).mapped('status')):
                lines = self.filtered(lambda rec: rec.task_id == task and rec.status == status)
                # Markup(...) % values: the names (models, jobs, actions) are escaped, not read as HTML.
                task.change_id.sudo().message_post(body=Markup(_(
                    "%(user)s set %(items)s to '%(status)s' on action '%(task)s'.")) % {
                    'user': self.env.user.name, 'items': ', '.join(lines.mapped('item_name')),
                    'status': labels[status], 'task': task.name})

    def _post_dropped_message(self):
        """A model / job taken out of an action drops its line: if the line had an answer, say so on the
        request's chatter (the answer, who gave it and when are gone with the line)."""
        answered = self.filtered(lambda rec: rec.status != 'todo')
        labels = dict(self._fields['status']._description_selection(self.env))
        for rec in answered:
            rec.task_id.change_id.sudo().message_post(body=Markup(_(
                "%(item)s was taken out of action '%(task)s': its answer '%(status)s' (by %(who)s) is dropped.")) % {
                'item': rec.item_name, 'task': rec.task_id.name, 'status': labels[rec.status],
                'who': rec.done_by_id.name or '-'})
