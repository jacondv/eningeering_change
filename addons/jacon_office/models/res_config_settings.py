from odoo import fields, models

from .jacon_office_document import DEFAULT_VERSIONS_TO_KEEP, VERSIONS_TO_KEEP_PARAM


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    jacon_office_versions_to_keep = fields.Integer(
        string="Previous Revs Kept",
        config_parameter=VERSIONS_TO_KEEP_PARAM,
        default=DEFAULT_VERSIONS_TO_KEEP,
        help="How many previous Revs of a document Odoo keeps. The oldest ones are deleted as new ones are made. 0 keeps none.",
    )
