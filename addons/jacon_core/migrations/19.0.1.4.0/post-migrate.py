from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """project.project.allocated_hours now defaults to the total of the
    project's tasks (still editable by hand). Odoo keeps the existing
    column's hand-entered values on upgrade, so recompute every project
    (archived included) once to start from the task totals."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    projects = env['project.project'].with_context(active_test=False).search([])
    env.add_to_compute(projects._fields['allocated_hours'], projects)
    projects.flush_model(['allocated_hours'])
