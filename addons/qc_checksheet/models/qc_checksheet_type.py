from odoo import _, api, fields, models
from odoo.exceptions import UserError

LAYOUTS = [
    ('standard', 'Standard'),
    ('panel_sticker', 'Panel & Sticker'),
]


class QcChecksheetType(models.Model):
    """Kind of check sheet (General, Hydraulic, ...). Its Code goes into the
    sheet's Number, and its Layout picks which content and PDF the sheet uses."""
    _name = 'qc.checksheet.type'
    _description = 'QC Check Sheet Type'
    _order = 'sequence, name'

    name = fields.Char(required=True)
    code = fields.Char(required=True, help="Used in the Number: QC-<Code>-<Model Name>, e.g. GE.")
    layout = fields.Selection(LAYOUTS, required=True, default='standard')
    required = fields.Boolean(
        string='Required for every Job', default=True,
        help="Every Job is expected to have a check sheet of this Type. The Job QC page "
             "and the Dashboard report a Job without one as missing it.")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    _code_unique = models.Constraint('UNIQUE(code)', 'This Code is already used by another Type.')

    @api.model
    def _required_types(self):
        """The active Types every Job is expected to have a sheet of, for the Model and Job progress counts."""
        return self.search([('required', '=', True)])

    def write(self, vals):
        if 'layout' in vals and self.env['qc.checksheet'].search_count([('type_id', 'in', self.ids)], limit=1):
            raise UserError(_("Layout can't be changed once a check sheet uses this Type."))
        return super().write(vals)
