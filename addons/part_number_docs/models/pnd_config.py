from odoo import api, fields, models

DEFAULT_ROOT = 'OneDrive - MAAS Group Holdings'
DEFAULT_MAX_MB = 20


class PndConfig(models.Model):
    """The settings of the module (one record). Managers change them here, in their own menu: the
    general Settings screen is for administrators only."""
    _name = 'pnd.config'
    _description = 'Part Documents Settings'

    name = fields.Char(default='Settings', readonly=True)
    sync_root_name = fields.Char(
        string="Synced Folder Name", default=DEFAULT_ROOT, required=True,
        help="The name of the folder OneDrive creates on each PC for the shared library. A path is kept from "
             "what follows it, so it is the same on every PC.")
    sharepoint_url = fields.Char(
        string="SharePoint Address", default='https://maasgroupholdings.sharepoint.com',
        help="The address of the company's SharePoint, with which a path of the shared folder becomes a link "
             "that opens in the browser. Leave it empty for no such link.")
    sharepoint_site = fields.Char(string="Site", default='/sites/JaconEng', help="The site that holds the library.")
    sharepoint_library = fields.Char(
        string="Library", default='Shared Documents',
        help="The library that the synchronised folder shows (the first folder of a path, e.g. JACON ENGINEERING, "
             "is that library: the rest of the path is inside it).")
    show_all_documents_menu = fields.Boolean(
        string="Show the \"All Documents\" menu", default=True,
        help="The plain list of every document (for those who may edit), next to the search page. "
             "Hide it if the search page is enough.")
    max_file_mb = fields.Integer(string="Largest File (MB)", default=DEFAULT_MAX_MB, required=True)

    _positive_size = models.Constraint('CHECK (max_file_mb > 0)', "The largest file must be at least 1 MB.")

    def write(self, vals):
        res = super().write(vals)
        if 'show_all_documents_menu' in vals:
            self._apply_menu_visibility()
        return res

    def _apply_menu_visibility(self):
        menu = self.env.ref('part_number_docs.menu_pnd_list', raise_if_not_found=False)
        if menu:
            menu.sudo().active = self[:1].show_all_documents_menu

    @api.model
    def _get(self):
        """The (only) settings record. It comes with the module (and is cached); it is made again only
        if someone deleted it."""
        record = self.env.ref('part_number_docs.config_default', raise_if_not_found=False)
        if record and record.exists():
            return record.sudo()
        return self.sudo().search([], limit=1) or self.sudo().create({})
