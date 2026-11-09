from odoo import _, api, fields, models
from odoo.exceptions import UserError


class QcChecksheetApproval(models.Model):
    """Check Sheet Approval row. Full Name/Signature/Date are intentionally
    not modeled as fields - they are never entered on the UI, only ever
    printed as blank cells for a wet signature (see techspec §2.2)."""
    _name = 'qc.checksheet.approval'
    _description = 'QC Check Sheet Approval'
    _inherit = ['qc.checksheet.lock.mixin']
    _order = 'sequence, id'

    checksheet_id = fields.Many2one('qc.checksheet', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    position = fields.Char(required=True)


class QcChecksheetHistory(models.Model):
    """One Revision History row per Revision, written by the workflow on
    qc.checksheet. While that Revision is a Draft, only its own row's
    Description, Date and Created By can be changed by hand (Created By
    starts as the user who made the Revision). A Revision carries its own
    copy of all earlier rows, so reprinting an old Revision doesn't show the
    rows that came after it. Rev is a fixed number, so reordering or removing
    rows can't change it."""
    _name = 'qc.checksheet.history'
    _description = 'QC Check Sheet Revision History'
    _inherit = ['qc.checksheet.lock.mixin']
    _order = 'rev, id'

    checksheet_id = fields.Many2one('qc.checksheet', required=True, ondelete='cascade')
    rev = fields.Integer(string='Rev', default=0)
    description = fields.Char()
    date = fields.Date(default=fields.Date.context_today)
    created_by = fields.Char(string='Created By', help="Starts as the user who created the Revision; can be changed while it is a Draft.")
    approved_by = fields.Char(string='Approved By')
    show_in_report = fields.Boolean(
        string='Show in Report', default=True,
        help="Uncheck to keep this revision in the record without printing it on the PDF.")

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            raise UserError(_("Revision History is written by the system."))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su:
            if vals.keys() - {'show_in_report', 'description', 'date', 'created_by'}:
                raise UserError(_("Revision History is written by the system."))
            if vals.keys() & {'description', 'date', 'created_by'}:
                for line in self:
                    if line.rev != line.checksheet_id.revision:
                        raise UserError(_(
                            "Only the row of the current Revision can be changed (Rev %s).",
                            line.checksheet_id.revision))
        return super().write(vals)

    def unlink(self):
        if not self.env.su:
            raise UserError(_("Revision History is written by the system."))
        return super().unlink()
