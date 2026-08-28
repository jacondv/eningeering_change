from odoo import api, fields, models


class EngineeringChangeChecklistLine(models.Model):
    _name = 'engineering.change.checklist.line'
    _description = 'Engineering Change Checklist Line'
    _order = 'section, sequence, id'

    change_id = fields.Many2one('engineering.change', required=True, ondelete='cascade')
    section = fields.Selection([
        ('design_document', 'Update Design Document'),
        ('goods_in_stock', 'Goods In Stock'),
        ('delivered_goods', 'Delivered Goods'),
    ], required=True, default='design_document')
    sequence = fields.Integer(default=10)
    name = fields.Char(required=True)
    is_checked = fields.Boolean(string='Work')
    date_done = fields.Date(string='Completed Date')
    completed_by_id = fields.Many2one('res.users', string='Completed By')

    @api.onchange('is_checked')
    def _onchange_is_checked(self):
        # Fires in an editable list row's own in-progress edit, before it's
        # saved - gives immediate visual feedback (date/user show up right
        # after ticking, no save needed). write() below mirrors both
        # directions again so the same happens when is_checked is set any
        # other way (e.g. a non-editable list's checkbox writes straight to
        # the server, bypassing this onchange entirely).
        for rec in self:
            if rec.is_checked:
                rec.completed_by_id = rec.completed_by_id or self.env.user
                rec.date_done = rec.date_done or fields.Date.context_today(rec)
            else:
                rec.completed_by_id = False
                rec.date_done = False

    def write(self, vals):
        if 'is_checked' not in vals:
            return super().write(vals)
        for rec in self:
            fill = dict(vals)
            if vals['is_checked']:
                if 'completed_by_id' not in vals and not rec.completed_by_id:
                    fill['completed_by_id'] = self.env.user.id
                if 'date_done' not in vals and not rec.date_done:
                    fill['date_done'] = fields.Date.context_today(rec)
            else:
                fill.setdefault('completed_by_id', False)
                fill.setdefault('date_done', False)
            super(EngineeringChangeChecklistLine, rec).write(fill)
        return True
