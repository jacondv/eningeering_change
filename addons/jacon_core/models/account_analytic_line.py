from odoo import fields, models


class AccountAnalyticLine(models.Model):
    _inherit = 'account.analytic.line'

    task_type = fields.Selection(
        related='task_id.task_type', store=True, string='Task Type')
