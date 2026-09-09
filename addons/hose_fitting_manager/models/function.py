from odoo import fields, models


class HoseAndFittingFunction(models.Model):
    """A fixed, shared pick-list of Functions for Hose And Fitting lines
    (e.g. "Suction", "Return", "Drain") - configured once here, then only
    ever selected (never free-typed) on the Job Hose Line / Builder page.
    Not tied to any Symbol/Config, and unrelated to part_number_manager.
    """
    _name = 'hose_fitting_manager.function'
    _description = 'Hose And Fitting Function'
    _order = 'sequence, id'

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
