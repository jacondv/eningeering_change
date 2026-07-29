import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { ImageField, imageField } from "@web/views/fields/image/image_field";
import { onMounted, onWillUnmount } from "@odoo/owl";

/**
 * Image field that also accepts an image straight from the clipboard: it
 * tries to read the clipboard as soon as it mounts (best-effort - browsers
 * that don't support/allow `navigator.clipboard.read()` without an explicit
 * user gesture, e.g. Firefox, just silently skip this), and always listens
 * for a Ctrl+V paste while it's on screen, which works everywhere.
 */
export class ClipboardImageField extends ImageField {
    setup() {
        super.setup();
        this.onPaste = this.onPaste.bind(this);
        onMounted(() => {
            document.addEventListener("paste", this.onPaste);
            this.tryAutoPasteFromClipboard();
        });
        onWillUnmount(() => {
            document.removeEventListener("paste", this.onPaste);
        });
    }

    get hasImage() {
        return Boolean(this.props.record.data[this.props.name]);
    }

    async tryAutoPasteFromClipboard() {
        if (this.hasImage || !navigator.clipboard?.read) {
            return;
        }
        try {
            const items = await navigator.clipboard.read();
            await this.insertFirstImage(items);
        } catch {
            // No permission granted yet, nothing to read, or unsupported
            // browser - the user can still paste manually with Ctrl+V.
        }
    }

    async onPaste(ev) {
        if (this.hasImage) {
            return;
        }
        const items = ev.clipboardData?.items;
        if (!items) {
            return;
        }
        for (const item of items) {
            if (item.type.startsWith("image/")) {
                ev.preventDefault();
                await this.insertBlob(item.getAsFile());
                return;
            }
        }
    }

    async insertFirstImage(clipboardItems) {
        for (const item of clipboardItems) {
            const imageType = item.types.find((type) => type.startsWith("image/"));
            if (imageType) {
                await this.insertBlob(await item.getType(imageType));
                return;
            }
        }
    }

    async insertBlob(blob) {
        const data = await this.blobToBase64(blob);
        await this.onFileUploaded({
            data,
            name: `clipboard.${blob.type.split("/")[1] || "png"}`,
            type: blob.type,
        });
    }

    blobToBase64(blob) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onloadend = () => resolve(reader.result.split(",")[1]);
            reader.onerror = reject;
            reader.readAsDataURL(blob);
        });
    }
}

export const clipboardImageField = {
    ...imageField,
    component: ClipboardImageField,
    displayName: _t("Image (Clipboard Paste)"),
};

registry.category("fields").add("clipboard_image", clipboardImageField);
