import logging
import re

from odoo import _, models

_logger = logging.getLogger(__name__)

# Matches an embedded image's attachment id out of Odoo's own editor-
# generated <img src="/web/image/473-31d6df3b/image.png?..."> markup - see
# _adopt_embedded_image_attachments.
IMG_ATTACHMENT_RE = re.compile(r'/web/image/(\d+)-')


class JaconHtmlAttachmentMixin(models.AbstractModel):
    """Mixin any model can inherit to guard its own Html field(s) against the
    "orphaned embedded image" failure mode - see _adopt_embedded_image_attachments.
    Originally written for engineering.change (the 2608-003 incident: an
    EC's Background/Description lost pasted images because their attachment
    never got linked to the record, and Odoo's own daily auto-vacuum cron
    permanently deleted them), pulled out here so every other Html field
    that lets someone paste an image gets the same protection.

    Usage from a model's own create()/write() override, after super():

        records._adopt_embedded_image_attachments(('description', 'notes'))
    """
    _name = 'jacon.html.attachment.mixin'
    _description = 'Mixin: guards embedded images in Html fields from going orphaned'

    def _adopt_embedded_image_attachments(self, field_names):
        """Claims every ir.attachment referenced by an <img> in `field_names`'
        HTML content that isn't already linked to this record, and warns
        (via Chatter) about any reference whose attachment is already gone.

        Odoo's HTML editor uploads a pasted image as its own ir.attachment
        immediately, then relies on the browser sending a second "link it to
        this record" call once the record is saved; when that second call
        doesn't happen (a client-side timing/JS quirk, not something this
        addon controls), the attachment sits "orphaned" (res_id=0) until
        Odoo's own daily auto-vacuum cron permanently deletes it. Doing the
        claim here, synchronously on every create/write, closes that window
        instead of just detecting the damage afterwards.

        Only ever adopts a genuinely orphaned attachment (res_id 0/empty) -
        never one already linked to some other real record. Without that
        guard this sudo() write would let anyone who can edit the field
        hijack an arbitrary attachment elsewhere in the system just by
        referencing its id in an <img> tag (the regex only reads the id out
        of the src, it never checks the checksum Odoo's own image route
        would enforce) - found and fixed during review of the first user of
        this mixin, engineering.change.
        """
        Attachment = self.env['ir.attachment'].sudo()
        for rec in self:
            att_ids = set()
            for field_name in field_names:
                att_ids |= {int(m) for m in IMG_ATTACHMENT_RE.findall(rec[field_name] or '')}
            if not att_ids:
                continue
            attachments = Attachment.browse(att_ids).exists()
            missing = att_ids - set(attachments.ids)
            to_adopt = attachments.filtered(lambda a: not a.res_id)
            if to_adopt:
                to_adopt.write({'res_model': rec._name, 'res_id': rec.id})
            if missing:
                message = _(
                    "⚠️ %(count)d image(s) referenced in this record's content "
                    "could not be found (upload may have failed) - please re-insert them.",
                    count=len(missing))
                # Not every model using this mixin has Chatter (e.g.
                # equipment.certificate) - fall back to a server log so the
                # gap is still visible somewhere instead of silently dropped.
                if hasattr(rec, 'message_post'):
                    rec.message_post(body=message)
                else:
                    _logger.warning(
                        "%s(%s): %s (missing attachment ids: %s)",
                        rec._name, rec.id, message, sorted(missing))
