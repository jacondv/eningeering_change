from odoo import fields, models


class HoseAndFittingConfig(models.Model):
    """Reusable engineering "recipe" for one Hose Symbol (e.g. "A"): which
    Hose Part, which Fire Wrap Part, and which Fitting Part variants are
    valid for position 1/2 - configured once, then auto-filled onto every
    Job Hose Line that picks this Symbol (see job_hose_line.py). Every
    Hose/Fitting/Ferrule/Fire Wrap referenced here is a real
    part_number_manager.part_number record - never a free-text code.
    Description text is never duplicated here - always read live from the
    referenced Part's own `display_description`.
    """
    _name = 'hose_fitting_manager.config'
    _description = 'Hose And Fitting Config'
    _order = 'symbol'
    _rec_name = 'symbol'

    symbol = fields.Char(required=True, index=True)
    hose_id = fields.Many2one(
        'part_number_manager.part_number', string='Hose', required=True,
        domain="[('part_type_id.name', '=', 'Hose')]")
    fire_wrap_option_ids = fields.One2many(
        'hose_fitting_manager.config_fire_wrap_option', 'config_id', string='Fire Wrap Options',
        help="Every Fire Wrap allowed for this Symbol - like Fitting Options, may have more than "
             "one (or none). Never applied by default on a Job Hose Line - always an explicit pick.")
    fitting1_option_ids = fields.One2many(
        'hose_fitting_manager.config_fitting_option', 'config_id', string='Fitting 1 Options',
        domain=[('slot', '=', '1')], context={'default_slot': '1'})
    fitting2_option_ids = fields.One2many(
        'hose_fitting_manager.config_fitting_option', 'config_id', string='Fitting 2 Options',
        domain=[('slot', '=', '2')], context={'default_slot': '2'})


class HoseAndFittingConfigFittingOption(models.Model):
    """One allowed Fitting variant (e.g. straight vs. 90 degree elbow) for
    position 1 or 2 of a Hose And Fitting Config. Each variant carries its
    own default Ferrule - the Ferrule needed depends on which exact Fitting
    is actually used, not on the Hose (a Fitting comes as a set with its
    own Ferrule, per techspec).
    """
    _name = 'hose_fitting_manager.config_fitting_option'
    _description = 'Hose And Fitting Config Fitting Option'
    _order = 'config_id, slot, sequence, id'

    config_id = fields.Many2one(
        'hose_fitting_manager.config', required=True, ondelete='cascade')
    slot = fields.Selection([('1', 'Fitting 1'), ('2', 'Fitting 2')], required=True)
    sequence = fields.Integer(default=10)
    fitting_id = fields.Many2one(
        'part_number_manager.part_number', string='Fitting', required=True,
        domain="[('part_type_id.name', '=', 'Fitting')]")
    ferrule_id = fields.Many2one(
        'part_number_manager.part_number', string='Ferrule',
        domain="[('part_type_id.name', '=', 'Ferrule')]",
        help="Optional - the Ferrule that goes with this exact Fitting variant, if any.")


class HoseAndFittingConfigFireWrapOption(models.Model):
    """One Fire Wrap allowed for a Hose And Fitting Config - a plain list
    (not tied to any particular Fitting/Hose choice), same idea as
    fitting1/2_option_ids: zero, one, or several may apply to a given
    Symbol, and none is ever pre-selected - only an explicit pick on the
    Job Hose Line counts.
    """
    _name = 'hose_fitting_manager.config_fire_wrap_option'
    _description = 'Hose And Fitting Config Fire Wrap Option'
    _order = 'config_id, sequence, id'

    config_id = fields.Many2one(
        'hose_fitting_manager.config', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    fire_wrap_id = fields.Many2one(
        'part_number_manager.part_number', string='Fire Wrap', required=True,
        domain="[('part_type_id.name', '=', 'Fire Wrap')]")
