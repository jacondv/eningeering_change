import uuid

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class QcChecksheetLockMixin(models.AbstractModel):
    """Child lines of a check sheet can only change while that sheet is a
    Draft. One2many edits on the sheet's form and the wizards both end up
    here, so this is the single place that enforces it."""
    _name = 'qc.checksheet.lock.mixin'
    _description = 'QC Check Sheet Child Line Lock'

    # Path from this model to its qc.checksheet.
    _checksheet_path = 'checksheet_id'

    def _check_checksheet_is_draft(self):
        if self.env.su:
            return
        for checksheet in self.sudo().mapped(self._checksheet_path):
            if checksheet.state != 'draft':
                raise UserError(_(
                    "%s is locked. Create a New Revision to change it.", checksheet.display_name))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._check_checksheet_is_draft()
        return records

    def write(self, vals):
        self._check_checksheet_is_draft()
        result = super().write(vals)
        # The line may have just been moved onto another check sheet.
        self._check_checksheet_is_draft()
        return result

    def unlink(self):
        self._check_checksheet_is_draft()
        return super().unlink()


class QcChecksheetKeyedLineMixin(models.AbstractModel):
    """Lines that keep the same line_key from one Revision to the next, so
    comparing Revisions can tell an edited line from a deleted and re-added
    one, even after rows were inserted or reordered."""
    _name = 'qc.checksheet.keyed.line.mixin'
    _description = 'QC Check Sheet Line With Stable Key'
    _inherit = ['qc.checksheet.lock.mixin']

    line_key = fields.Char(readonly=True, default=lambda self: uuid.uuid4().hex)
