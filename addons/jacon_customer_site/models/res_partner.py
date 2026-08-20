from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    type = fields.Selection(
        selection_add=[('site', 'Site')],
        ondelete={'site': 'set default'})

    site_ids = fields.Many2many(
        'res.partner', 'res_partner_site_customer_rel', 'customer_id', 'site_id',
        string='Sites', domain=[('type', '=', 'site')],
        help="Delivery sites linked to this Customer, for quick selection "
             "when picking a Project's Site.")
    customer_ids = fields.Many2many(
        'res.partner', 'res_partner_site_customer_rel', 'site_id', 'customer_id',
        string='Customers', domain=[('type', '!=', 'site')],
        help="Customers linked to this Site. A Site does not require any "
             "Customer and can be linked to more than one.")
