import difflib

from lxml import html as lxml_html

from odoo import _, api, fields, models
from odoo.tools import html2plaintext


class JaconFieldChangeLogMixin(models.AbstractModel):
    """Mixin any model can inherit to get evidence-trail logging (see
    jacon.field.change.log) for its own HTML fields, plus a ready-made
    "History" smart button - without each model having to define its own
    log model/ACL/view. Usage from a model's own write() override:

        old_value = record.some_html_field
        result = super().write(vals)
        if 'some_html_field' in vals:
            record._log_html_field_change('some_html_field', old_value)

    Comparing on html2plaintext output (not raw HTML) so a purely cosmetic
    edit (bold, color...) that doesn't change the actual text doesn't get
    logged as a change. difflib with n=0 keeps only the actually-differing
    lines, not surrounding unchanged context, so the stored diff stays
    proportional to how much really changed, not to the field's overall
    length.
    """
    _name = 'jacon.field.change.log.mixin'
    _description = 'Mixin: HTML field change history (diff-based evidence trail)'

    # Not a real relational field (jacon.field.change.log is a shared,
    # polymorphic table, not a one2many target) so there's nothing for
    # @api.depends to track - always recomputed fresh (e.g. on every form
    # load) rather than cached/invalidated off some other field's write.
    field_change_log_count = fields.Integer(compute='_compute_field_change_log_count')

    @api.depends()
    def _compute_field_change_log_count(self):
        Log = self.env['jacon.field.change.log'].sudo()
        for rec in self:
            rec.field_change_log_count = Log.search_count([
                ('res_model', '=', rec._name), ('res_id', '=', rec.id)])

    def _log_html_field_change(self, field_name, old_value):
        """Returns True if a diff was actually logged (i.e. `field_name`'s
        plain-text content really changed) - callers that also want to
        notify someone about the change (e.g. project.task's Chatter/popup)
        can key off this instead of re-deriving the same comparison."""
        self.ensure_one()
        old_text = html2plaintext(self._html_images_to_text(old_value)).splitlines()
        new_text = html2plaintext(self._html_images_to_text(self[field_name])).splitlines()
        if old_text == new_text:
            return False
        diff_lines = [
            line for line in difflib.unified_diff(old_text, new_text, lineterm='', n=0)
            if line.startswith(('+', '-')) and not line.startswith(('+++', '---'))
        ]
        if not diff_lines:
            return False
        self.env['jacon.field.change.log'].sudo().create({
            'res_model': self._name,
            'res_id': self.id,
            'field_name': field_name,
            'diff': '\n'.join(diff_lines),
        })
        return True

    def _html_images_to_text(self, html_content):
        """Replaces every <img src="..."> in `html_content` with a plain-text
        "[Image] <full url>" line before it goes through html2plaintext
        (which otherwise drops <img> tags with no trace) - so an image
        being added/removed/swapped shows up in the diff as a
        copy-pasteable URL to open it, instead of silently vanishing. A
        relative src (Odoo's own attachment URLs, e.g.
        "/web/image/874-xxx/image.png?access_token=...") is turned absolute
        via get_base_url() so it's still usable pasted outside Odoo.
        """
        if not html_content:
            return ''
        try:
            root = lxml_html.fragment_fromstring(html_content, create_parent='div')
        except Exception:
            return html_content
        base_url = self.get_base_url()
        for img in root.findall('.//img'):
            src = img.get('src') or ''
            if src.startswith('/'):
                src = base_url + src
            placeholder = root.makeelement('span')
            placeholder.text = f'[Image] {src}'
            img.getparent().replace(img, placeholder)
        return lxml_html.tostring(root, encoding='unicode')

    def action_view_field_change_log(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Change History'),
            'res_model': 'jacon.field.change.log',
            'view_mode': 'list,form',
            'domain': [('res_model', '=', self._name), ('res_id', '=', self.id)],
        }
