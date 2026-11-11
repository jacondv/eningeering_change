from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Last Job Number is new: start every Group from its highest Job number in use."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['equipment.model.category'].search([])._fill_last_job_numbers()
