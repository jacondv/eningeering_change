from odoo import api, fields, models


class ProjectProject(models.Model):
    _inherit = 'project.project'

    site_id = fields.Many2one(
        'res.partner', string='Site', domain=[('type', '=', 'site')],
        context={'default_type': 'site'},
        help="Delivery site for this project's equipment. Not required to "
             "belong to the selected Customer - a Site can be shared by "
             "several Customers or stand on its own.")

    @api.onchange('partner_id')
    def _onchange_partner_id_suggest_site(self):
        if self.partner_id and not self.site_id and self.partner_id.site_ids:
            self.site_id = self.partner_id.site_ids[0]
