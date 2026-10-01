from odoo import api, models
from odoo.fields import Domain

VENDOR_DISPLAY_CONTEXT = 'pnm_vendor_display'


class ResPartner(models.Model):
    _inherit = 'res.partner'

    @api.depends_context(VENDOR_DISPLAY_CONTEXT)
    def _compute_display_name(self):
        super()._compute_display_name()
        # "<Vendor Code> - <Vendor Name>" only inside the Part Number module
        # (views pass this context) - Contacts, POs, invoices are unchanged.
        if self.env.context.get(VENDOR_DISPLAY_CONTEXT):
            for partner in self:
                partner.display_name = partner._pnm_vendor_label()

    def _pnm_vendor_label(self):
        self.ensure_one()
        code = (self.ref or '').strip()
        name = (self.name or '').strip()
        # A Vendor created with only a code stores that code as its name too
        # (Odoo requires a name) - shown once, not "X - X".
        if code and name and code != name:
            return f'{code} - {name}'
        return code or name

    def _pnm_vendor_option(self):
        return {'id': self.id, 'label': self._pnm_vendor_label()}

    @api.model
    def pnm_search_vendors(self, text, limit=20):
        """Create/Convert page's Vendor dropdown: match by name or code."""
        text = (text or '').strip()
        domain = Domain.OR([[('name', 'ilike', text)], [('ref', 'ilike', text)]]) if text else Domain.TRUE
        return [partner._pnm_vendor_option() for partner in self.search(domain, limit=limit, order='ref, name')]

    @api.model
    def pnm_match_vendor(self, text):
        """Exact match of pasted/typed text: code, then name, then the full
        "<code> - <name>" label. False when nothing (or more than one Vendor
        by name) matches - the user then picks or creates one explicitly."""
        text = (text or '').strip()
        if not text:
            return False
        by_code = self.search([('ref', '=ilike', text)], limit=1)
        if by_code:
            return by_code._pnm_vendor_option()
        by_name = self.search([('name', '=ilike', text)], limit=2)
        if len(by_name) == 1:
            return by_name._pnm_vendor_option()
        code, sep, name = text.partition(' - ')
        if sep:
            by_label = self.search([('ref', '=ilike', code.strip()), ('name', '=ilike', name.strip())], limit=1)
            if by_label:
                return by_label._pnm_vendor_option()
        return False

    @api.model
    def pnm_create_vendor(self, name, code, allow_same_name=False):
        """Create Vendor dialog. Needs a name or a code (either is enough).
        A code already used blocks creation (Vendor Code is unique) and hands
        back that Vendor to use instead; an identical name only asks first,
        since two companies can share a name."""
        name = (name or '').strip()
        code = (code or '').strip()
        if not (name or code):
            return {'status': 'missing'}
        if code:
            existing = self.search([('ref', '=ilike', code)], limit=1)
            if existing:
                return {'status': 'duplicate_code', 'vendor': existing._pnm_vendor_option()}
        if name and not allow_same_name:
            existing = self.search([('name', '=ilike', name)], limit=1)
            if existing:
                return {'status': 'same_name', 'vendor': existing._pnm_vendor_option()}
        vendor = self.create({'name': name or code, 'ref': code or False, 'is_company': True})
        return {'status': 'created', 'vendor': vendor._pnm_vendor_option()}
