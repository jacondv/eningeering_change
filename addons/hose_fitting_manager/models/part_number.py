from odoo import fields, models


class PartNumber(models.Model):
    """Hose and Fitting-specific extension of part_number_manager's own
    Part Number - kept in this module (not the core one) since Length/BOM
    only ever matter for a "Hose and Fitting" assembly, not Part Numbers
    in general.
    """
    _inherit = 'part_number_manager.part_number'

    bom_line_ids = fields.One2many(
        'hose_fitting_manager.bom_line', 'parent_part_id', string='BOM',
        help="Components this assembled Hose and Fitting Part is actually built from.")
    length = fields.Float(
        help="Cut length for an assembled Hose and Fitting Part - meaningless for any other Part.")
    length_tolerance = fields.Float(
        default=100.0,
        help="How far a requested Length may differ from this Part's own Length and still be "
             "considered a reusable match by the Hose & Fitting Builder page (e.g. 100mm). Set "
             "per Part, not globally - defaults to 100 on creation.")
