import { FileModel } from "@web/core/file_viewer/file_model";
import { useFileViewer } from "@web/core/file_viewer/file_viewer_hook";
import { registry } from "@web/core/registry";
import {
    Many2ManyBinaryField,
    many2ManyBinaryField,
} from "@web/views/fields/many2many_binary/many2many_binary_field";

// many2many_binary whose thumbnail/name open Odoo's own file viewer (the one
// the chatter uses) for images, PDF, video and text; other types still download.
export class Many2ManyBinaryPreviewField extends Many2ManyBinaryField {
    static template = "jacon_product_support.Many2ManyBinaryPreviewField";

    setup() {
        super.setup();
        this.fileViewer = useFileViewer();
    }

    onFileClick(ev, file) {
        const files = this.files.map((f) =>
            Object.assign(new FileModel(), { id: f.id, name: f.name, mimetype: f.mimetype })
        );
        const target = files.find((f) => f.id === file.id);
        if (!target?.isViewable) {
            return;
        }
        ev.preventDefault();
        this.fileViewer.open(target, files);
    }
}

registry.category("fields").add("many2many_binary_preview", {
    ...many2ManyBinaryField,
    component: Many2ManyBinaryPreviewField,
});
