from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    pnm_require_edit_password = fields.Boolean(
        string='Require password to edit Part Numbers',
        config_parameter='part_number_manager.require_edit_password',
        help="When enabled, an existing Part Number is read-only until the Edit button on its "
             "form is used with the current user's own password (see is_unlocked on "
             "part_number.py). When disabled, every Part Number is always directly editable, "
             "no password step.")
