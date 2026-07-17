import base64
import re

from odoo import fields, models
from odoo.tools.image import image_data_uri

# Illustrator's SVG export can embed text using the legacy "SVG Fonts"
# format (@font-face ... format(svg) + a matching <font> glyph block).
# Browsers dropped support for this years ago and silently fall back to
# a real system font, but wkhtmltopdf still honors it - if the embedded
# glyph set is incomplete, letters go missing in the PDF. Stripping both
# out forces the same font-fallback behavior browsers already use.
_SVG_FONT_FACE_RE = re.compile(rb'@font-face\s*\{[^}]*format\(svg\)[^}]*\}')
_SVG_FONT_ELEMENT_RE = re.compile(rb'<font\b.*?</font>', re.DOTALL)


class QcChecksheetPanelLine(models.Model):
    """Panel & Sticker line. Every field is entered by hand - no lookup
    against product.product - except item_number/part_number/description/
    qty/image, which can also be brought in wholesale from an Inventor BOM
    via the Import wizard."""
    _name = 'qc.checksheet.panel.line'
    _description = 'QC Check Sheet Panel Line'
    _order = 'sequence, id'

    checksheet_id = fields.Many2one('qc.checksheet', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    item_number = fields.Integer(
        string='Item',
        help="Printed as-is in the Item column - left blank if not set, never auto-numbered.")
    part_number = fields.Char(string='Part Number')
    description = fields.Char()
    image = fields.Image(max_width=1920, max_height=1920)
    qty = fields.Float(string='Qty', default=1.0)
    note = fields.Char()

    def _pdf_safe_image_data_uri(self):
        """image_data_uri(self.image), with embedded SVG-font glyphs
        stripped first - the stored image itself is left untouched."""
        self.ensure_one()
        source = self.image
        if not source:
            return ''
        if source[:1] in (b'P', 'P'):
            svg = base64.b64decode(source)
            svg = _SVG_FONT_FACE_RE.sub(b'', svg)
            svg = _SVG_FONT_ELEMENT_RE.sub(b'', svg)
            source = base64.b64encode(svg)
        return image_data_uri(source)
