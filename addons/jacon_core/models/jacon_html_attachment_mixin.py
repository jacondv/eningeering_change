import logging
import re

from odoo import _, models
from odoo.tools import consteq

_logger = logging.getLogger(__name__)

# Matches an embedded image's attachment id out of Odoo's own editor-
# generated <img src="/web/image/473-31d6df3b/image.png?..."> markup - see
# _adopt_embedded_image_attachments.
IMG_ATTACHMENT_RE = re.compile(r'/web/image/(\d+)-')
# Same markup, this time the whole src: (full src, attachment id, checksum
# prefix) - see _copy_borrowed_images. The editor's copy turns a src absolute,
# so that's what a pasted image comes with.
IMG_SRC_RE = re.compile(r'src="((?:https?://[^/"]+)?/web/image/(\d+)-([0-9a-f]+)[^"]*)"')
IMG_ACCESS_TOKEN_RE = re.compile(r'[?&;]access_token=([^&"]+)')


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

        It must also have been uploaded *for this model* (res_model ==
        rec._name, which is what the editor sends when uploading from the
        record's own form). res_id=0 alone isn't enough: html_editor stores
        the shared Media Library / website images as res_model='ir.ui.view',
        res_id=0 - adopting one of those just because someone inserted it
        here would pull it out of the Media Library for everyone, and
        deleting this record would then delete it everywhere it's used.
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
            to_adopt = attachments.filtered(
                lambda a: not a.res_id and a.res_model == rec._name)
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
        self._copy_borrowed_images(field_names)

    def _copy_borrowed_images(self, field_names):
        """Gives this record its own copy of every image in `field_names`
        that still belongs to another record, and points the <img> at it.

        Copy/pasting an image between Html fields only carries its src, while
        the attachment stays linked to the record it was uploaded on - and
        deleting that record deletes the attachment, breaking the image
        everywhere it was pasted. The copy shares the same file on disk, so
        this costs no storage.

        Goes through write() rather than around it so html_field_history's
        patches keep applying to the stored content, which does add a version
        to it. Not a user edit though, so jacon.field.change.log.mixin skips it.
        """
        for rec in self:
            local_srcs = {}

            def local_src(match):
                src = match[1]
                if src not in local_srcs:
                    attachment = rec._get_borrowed_attachment(int(match[2]), match[3], src)
                    local_srcs[src] = attachment and rec._copy_image_attachment(attachment)
                return f'src="{local_srcs[src]}"' if local_srcs[src] else match[0]

            vals = {}
            for field_name in field_names:
                content = rec[field_name] or ''
                new_content = IMG_SRC_RE.sub(local_src, content)
                if new_content != content:
                    vals[field_name] = new_content
            if vals:
                rec.with_context(skip_html_change_log=True).write(vals)

    def _get_borrowed_attachment(self, attachment_id, checksum_prefix, src):
        """The attachment behind `src` if it's one this record should copy.

        This runs in sudo on an id read out of content the user wrote, so it
        must not become a way to read an attachment they couldn't otherwise
        see: the src has to carry the attachment's real checksum, and either
        its access token or a user who has read access to it. The checksum
        also catches a src whose id now means an unrelated attachment.

        Shared Media Library / public images don't depend on any record, so
        there's nothing to protect them from - see
        _adopt_embedded_image_attachments for the same distinction.
        """
        self.ensure_one()
        Attachment = self.env['ir.attachment']
        attachment = Attachment.sudo().browse(attachment_id).exists()
        if (not attachment
                or attachment.public
                or attachment.res_model == 'ir.ui.view'
                or attachment.res_field
                or not attachment.image_src
                or attachment.checksum[:len(checksum_prefix)] != checksum_prefix
                or (attachment.res_model == self._name and attachment.res_id == self.id)):
            return Attachment
        token = IMG_ACCESS_TOKEN_RE.search(src)
        if token and consteq(attachment.access_token or '', token[1]):
            return attachment
        return attachment if Attachment.browse(attachment_id).has_access('read') else Attachment

    def _copy_image_attachment(self, attachment):
        """Copies `attachment` onto this record, returning the new image's src."""
        self.ensure_one()
        image = attachment.copy({'res_model': self._name, 'res_id': self.id, 'access_token': False})
        image.generate_access_token()
        return f'{image.image_src}?access_token={image.access_token}'
