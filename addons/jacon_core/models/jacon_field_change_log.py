from odoo import fields, models


class JaconFieldChangeLog(models.Model):
    """One immutable row per edit to an HTML field on ANY model that mixes
    in jacon.field.change.log.mixin - who changed it, when, and a
    line-level diff (added/removed lines only, plain text; images captured
    as their full URL). `res_model`/`res_id`/`field_name` identify which
    record and field the edit belongs to - a single shared table instead of
    a separate log model per (model, field) pair. See
    JaconFieldChangeLogMixin._log_html_field_change, the only place that
    ever creates these rows.
    """
    _name = 'jacon.field.change.log'
    _description = 'Field Change Log'
    _order = 'date desc, id desc'

    res_model = fields.Char(required=True, index=True)
    res_id = fields.Integer(required=True, index=True)
    field_name = fields.Char(required=True)
    user_id = fields.Many2one('res.users', required=True, default=lambda self: self.env.user)
    date = fields.Datetime(required=True, default=fields.Datetime.now)
    diff = fields.Text(required=True)
