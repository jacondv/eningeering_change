from odoo import fields, models


class ProjectProject(models.Model):
    _inherit = 'project.project'

    po_received_date = fields.Date(string='PO Received Date')
    iof_release_date = fields.Date(string='IOF Release')
    bom_release_date = fields.Date(string='BOM Release')
    drawing_release_date = fields.Date(string='Drawing Release')
    qc_checksheet_date = fields.Date(string='QC Checksheet')
    photo_taken_date = fields.Date(string='Photo Taken')
    project_events_note = fields.Text(string='Note')
