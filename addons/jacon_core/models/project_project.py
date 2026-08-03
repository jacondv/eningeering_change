from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ProjectProject(models.Model):
    _inherit = 'project.project'

    po_number = fields.Char(string='PO Number')
    po_received_date = fields.Date(string='PO Received')
    iof_release_date = fields.Date(string='IOF Release')
    bom_release_date = fields.Date(string='BOM Release')
    drawing_release_date = fields.Date(string='Drawing Release')
    qc_checksheet_date = fields.Date(string='QC Checksheet')
    photo_taken_date = fields.Date(string='Photo Taken')
    dispatch_date = fields.Date(string='Dispatch Date')
    project_events_note = fields.Text(string='Note')

    machine_serial = fields.Char(string='Machine Serial')
    engine_serial = fields.Char(string='Engine Serial')
    vin_tin = fields.Char(string='VIN/TIN')

    site_id = fields.Many2one(
        'res.partner', string='Site',
        help="Delivery site for this project's equipment - a child contact "
             "of the Customer (address type 'Site'). Typing a new name "
             "creates it directly under the selected Customer.")

    @api.onchange('partner_id')
    def _onchange_partner_id_clear_stale_site(self):
        if self.site_id and self.site_id.parent_id != self.partner_id:
            self.site_id = False

    @api.constrains('partner_id', 'site_id')
    def _check_site_belongs_to_partner(self):
        for project in self:
            if project.site_id and project.site_id.parent_id != project.partner_id:
                raise ValidationError(_(
                    "The Site '%(site)s' does not belong to the Customer "
                    "'%(partner)s'.",
                    site=project.site_id.display_name,
                    partner=project.partner_id.display_name or _("(none)"),
                ))
