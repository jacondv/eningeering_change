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
    template_position_id = fields.Many2one(
        'qc.checksheet.template.approval', readonly=True, copy=False,
        help="Set when this row was seeded from the Template's default list - lets "
             "'Update Common Info' tell seeded rows (even renamed) apart from custom ones, "
             "without relying on a text match.")


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
