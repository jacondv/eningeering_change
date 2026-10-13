from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class HoseAndFittingConfig(models.Model):
    """Reusable engineering "recipe" for one Hose Symbol (e.g. "A"): which
    Hose Part, which Fire Wrap Part, and which Fitting Part variants are
    valid on the hose's ends - configured once, then auto-filled onto every
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
    hose_guard_option_ids = fields.One2many(
        'hose_fitting_manager.config_hose_guard_option', 'config_id', string='Hose Guard Options',
        help="Every Hose Guard allowed for this Symbol - same idea as Fire Wrap Options: may have "
             "more than one (or none), never applied by default - always an explicit pick.")
    # One list for both ends: Fitting 1 and Fitting 2 always allow the same
    # variants, so they're entered once (they used to be two lists, kept in
    # sync by hand - see migrations/19.0.1.1.0).
    fitting_option_ids = fields.One2many(
        'hose_fitting_manager.config_fitting_option', 'config_id', string='Fitting Options',
        help="Every Fitting variant allowed on this Symbol's hose - offered for both Fitting 1 "
             "and Fitting 2 on a Job Hose Line.")


class HoseAndFittingConfigFittingOption(models.Model):
    """One allowed Fitting variant (e.g. straight vs. 90 degree elbow) of a
    Hose And Fitting Config, for either end of the hose. Each variant carries its
    own default Ferrule - the Ferrule needed depends on which exact Fitting
    is actually used, not on the Hose (a Fitting comes as a set with its
    own Ferrule, per techspec).
    """
    _name = 'hose_fitting_manager.config_fitting_option'
    _description = 'Hose And Fitting Config Fitting Option'
    _order = 'config_id, sequence, id'

    config_id = fields.Many2one(
        'hose_fitting_manager.config', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    fitting_id = fields.Many2one(
        'part_number_manager.part_number', string='Fitting', required=True,
        domain="[('part_type_id.name', '=', 'Fitting')]")
    ferrule_id = fields.Many2one(
        'part_number_manager.part_number', string='Ferrule',
        domain="[('part_type_id.name', '=', 'Ferrule')]",
        help="Optional - the Ferrule that goes with this exact Fitting variant, if any.")

    # Checked in Python, not as a SQL unique constraint - Ferrule is
    # optional, and SQL treats two empty Ferrules as different values.
    @api.constrains('config_id', 'fitting_id', 'ferrule_id')
    def _check_unique_fitting_ferrule(self):
        for option in self:
            duplicate = self.search_count([
                ('id', '!=', option.id),
                ('config_id', '=', option.config_id.id),
                ('fitting_id', '=', option.fitting_id.id),
                ('ferrule_id', '=', option.ferrule_id.id),
            ])
            if duplicate:
                raise ValidationError(_(
                    "%(fitting)s is already in this Symbol's Fitting Options with the same Ferrule.",
                    fitting=option.fitting_id.display_name))


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


class HoseAndFittingConfigHoseGuardOption(models.Model):
    """One Hose Guard allowed for a Hose And Fitting Config - same idea as
    HoseAndFittingConfigFireWrapOption: a plain list, zero/one/several may
    apply to a given Symbol, never pre-selected.
    """
    _name = 'hose_fitting_manager.config_hose_guard_option'
    _description = 'Hose And Fitting Config Hose Guard Option'
    _order = 'config_id, sequence, id'

    config_id = fields.Many2one(
        'hose_fitting_manager.config', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    hose_guard_id = fields.Many2one(
        'part_number_manager.part_number', string='Hose Guard', required=True,
        domain="[('part_type_id.name', '=', 'Hose Guard')]")
