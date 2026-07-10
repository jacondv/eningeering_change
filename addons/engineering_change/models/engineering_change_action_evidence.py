from odoo import _, api, fields, models


class EngineeringChangeActionEvidence(models.Model):
    _name = 'engineering.change.action.evidence'
    _description = 'Engineering Change Action Evidence'

    task_id = fields.Many2one('project.task', required=True, ondelete='cascade',
                               domain=[('change_id', '!=', False)])
    attachment = fields.Binary(required=True)
    attachment_filename = fields.Char(string='File Name')
    description = fields.Char(required=True, help='Explain what this evidence demonstrates.')
    upload_uid = fields.Many2one('res.users', string='Uploaded By', readonly=True, default=lambda self: self.env.user)
    upload_date = fields.Datetime(string='Upload Date', readonly=True, default=fields.Datetime.now)

    def action_open_attachment(self):
        """Open the evidence file directly, for use as a button on list rows
        (the `attachment` Binary field itself isn't a click target for
        opening the file once the list is editable).

        No `download=true`: /web/content then serves the file with a plain
        (non-attachment) Content-Disposition, so the browser renders it
        inline when it can (PDF, images...) instead of always forcing a
        download dialog.
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s/%s/attachment?filename=%s' % (
                self._name, self.id, self.attachment_filename or ''),
            'target': 'new',
        }

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            # sudo: whoever is allowed to add evidence on a task (assignee,
            # Request/BOD Approve, Manager...) isn't guaranteed write access
            # of their own on that specific task record.
            rec.task_id.sudo().message_post(
                body=_("Evidence '%s' added by %s.") % (rec.description, self.env.user.name))
        return records

    def unlink(self):
        for rec in self:
            rec.task_id.sudo().message_post(
                body=_("Evidence '%s' removed by %s.") % (rec.description, self.env.user.name))
        return super().unlink()
