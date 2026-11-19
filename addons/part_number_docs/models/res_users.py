from odoo import fields, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    pnd_windows_folder = fields.Char(
        string="Windows Folder", copy=False,
        help="The user's folder on their own PC (C:\\Users\\Name), where OneDrive keeps the shared folder. "
             "Set from the Part Documents page; it lets a path of the shared folder open on this PC.")
