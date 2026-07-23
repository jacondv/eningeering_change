from odoo import api, fields, models


class QcChecksheetApproval(models.Model):
    """Check Sheet Approval row. Full Name/Signature/Date are intentionally
    not modeled as fields - they are never entered on the UI, only ever
    printed as blank cells for a wet signature (see techspec §2.2)."""
    _name = 'qc.checksheet.approval'
    _description = 'QC Check Sheet Approval'
    _order = 'sequence, id'

    checksheet_id = fields.Many2one('qc.checksheet', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    position = fields.Char(required=True)


class QcChecksheetHistory(models.Model):
    _name = 'qc.checksheet.history'
    _description = 'QC Check Sheet Template History'
    _order = 'sequence, id'

    checksheet_id = fields.Many2one('qc.checksheet', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    rev = fields.Integer(string='Rev', compute='_compute_rev', store=True)
    description = fields.Char()
    date = fields.Date()
    created_by = fields.Char(string='Created By')
    approved_by = fields.Char(string='Approved By')
    show_in_report = fields.Boolean(
        string='Show in Report', default=True,
        help="Uncheck to keep this revision in the record without printing it on the PDF.")

    @api.depends('sequence', 'checksheet_id.history_ids.sequence')
    def _compute_rev(self):
        for checksheet in self.checksheet_id:
            lines = checksheet.history_ids.sorted(lambda h: (h.sequence, h.id))
            for index, line in enumerate(lines, start=1):
                if line in self:
                    line.rev = index
        # Lines not attached to any checksheet yet still need a value.
        for line in self:
            if not line.checksheet_id:
                line.rev = 1
