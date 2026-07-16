from odoo import fields, models


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
    rev = fields.Char(string='Rev')
    description = fields.Char()
    date = fields.Date()
    created_by = fields.Char(string='Created By')
    approved_by = fields.Char(string='Approved By')
