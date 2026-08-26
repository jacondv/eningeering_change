from odoo import fields, models


class HoseFittingBomLine(models.Model):
    """One component of an actually-assembled "Hose and Fitting" Part
    Number's real BOM - created when a Job Hose Line resolves/generates its
    assembly Part (see job_hose_line.py). `role` distinguishes which slot
    each component fills; a real assembly may have anywhere from 3 (Hose +
    2 Fittings) to 6 lines (+ up to 2 Ferrules + Fire Wrap) - never a fixed
    count, matched as a whole against `job_hose_line.find_matches`.
    """
    _name = 'hose_fitting_manager.bom_line'
    _description = 'Hose And Fitting BOM Line'
    _order = 'parent_part_id, sequence, id'

    parent_part_id = fields.Many2one(
        'part_number_manager.part_number', required=True, ondelete='cascade', index=True,
        help="The assembled Hose and Fitting Part Number this component belongs to.")
    component_part_id = fields.Many2one(
        'part_number_manager.part_number', required=True, string='Component')
    role = fields.Selection([
        ('hose', 'Hose'),
        ('fitting', 'Fitting'),
        ('ferrule', 'Ferrule'),
        ('fire_wrap', 'Fire Wrap'),
    ], required=True)
    sequence = fields.Integer(default=10)
