from odoo import api, fields, models

from .project_task import TASK_TYPE_SELECTION


class TimesheetsAnalysisReport(models.Model):
    """The stock Timesheet report (`timesheets.analysis.report`) is a SQL
    view built from `account_analytic_line` (see hr_timesheet's own
    `timesheets_analysis_report.py`), so a new stored field on that table
    doesn't appear here automatically - it must be added to both the field
    list and the underlying SELECT.

    Also: hr_timesheet's own `hr_timesheet_report_search` view re-parents
    the whole `hr_timesheet_line_search` arch (account.analytic.line) onto
    this model via `inherit_id` + `mode="primary"`, so any field jacon_core
    adds to that search view must exist here too, or the report screen
    breaks with "Unknown field" client-side.
    """
    _inherit = 'timesheets.analysis.report'

    task_type = fields.Selection(TASK_TYPE_SELECTION, string='Task Type', readonly=True)

    @api.model
    def _select(self):
        return super()._select() + ", A.task_type AS task_type"
