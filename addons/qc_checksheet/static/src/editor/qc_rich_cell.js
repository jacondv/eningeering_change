/** @odoo-module **/

import { Component, markup, onWillUnmount, useEffect, useRef } from "@odoo/owl";
import { MAIN_PLUGINS, NO_EMBEDDED_COMPONENTS_FALLBACK_PLUGINS } from "@html_editor/plugin_sets";
import { Wysiwyg } from "@html_editor/wysiwyg";

/**
 * One editable piece of Html. A cell only runs the real editor while it is the
 * active one and shows plain rendered Html otherwise, so a sheet with hundreds
 * of Items stays fast: the page keeps at most one editor alive at a time.
 */
export class QcRichCell extends Component {
    static template = "qc_checksheet.RichCell";
    static components = { Wysiwyg };
    static props = {
        value: String,
        active: Boolean,
        readonly: Boolean,
        label: String,
        placeholder: { type: String, optional: true },
        resModel: String,
        resId: { type: [Number, Boolean], optional: true },
        onActivate: Function,
        onChange: Function,
        onKeydown: Function,
        onPaste: { type: Function, optional: true },
        registerCommit: Function,
    };

    setup() {
        this.root = useRef("root");
        this.editor = null;
        // The picture clicked while the cell was still plain Html: selected once the editor is there, so the
        // editor's picture toolbar (Resize, Transform, ...) is there at once.
        this.pendingImageIndex = null;

        useEffect(
            (editing) => {
                if (editing && this.editor) {
                    this.props.registerCommit(() => this.commit());
                    this.placeCaret();
                    this.selectPendingImage();
                }
            },
            () => [this.editing]
        );
        onWillUnmount(() => {
            if (this.editing) {
                this.props.registerCommit(null);
            }
        });
    }

    get editing() {
        return this.props.active && !this.props.readonly;
    }

    get renderedValue() {
        return markup(this.props.value || "");
    }

    get isEmpty() {
        return !this.props.value || !/\S|<img/.test(this.props.value.replace(/<(?!img)[^>]*>|&nbsp;/g, ""));
    }

    get config() {
        return {
            content: markup(this.props.value || ""),
            Plugins: [...MAIN_PLUGINS, ...NO_EMBEDDED_COMPONENTS_FALLBACK_PLUGINS],
            baseContainers: ["P"],
            dropImageAsAttachment: true,
            placeholder: this.props.placeholder,
            onChange: () => this.onEditorChange(),
            getRecordInfo: () => ({
                resModel: this.props.resModel,
                // 0 until the row is saved, when the server claims the image
                // (see _adopt_embedded_image_attachments).
                resId: this.props.resId || 0,
            }),
            resources: {},
        };
    }

    onEditorLoad(editor) {
        this.editor = editor;
    }

    onEditorChange() {
        if (this.editor) {
            this.props.onChange(this.editor.getContent());
        }
    }

    // Pictures

    /**
     * Pressing the mouse on a picture of a cell that isn't being edited yet: the cell opens with that picture
     * selected. This has to be the mouse press, not the click: the press focuses the cell, which opens it
     * before any click is sent.
     */
    onRenderedMouseDown(ev) {
        if (ev.target instanceof HTMLImageElement) {
            this.pendingImageIndex = [...ev.currentTarget.querySelectorAll("img")].indexOf(ev.target);
        }
    }

    onRenderedClick() {
        this.props.onActivate();
    }

    selectPendingImage() {
        const index = this.pendingImageIndex;
        this.pendingImageIndex = null;
        const image = index === null ? null : this.editor.editable.querySelectorAll("img")[index];
        if (!image) {
            return;
        }
        const parent = image.parentNode;
        const at = [...parent.childNodes].indexOf(image);
        this.editor.shared.selection.setSelection(
            { anchorNode: parent, anchorOffset: at, focusNode: parent, focusOffset: at + 1 },
            { normalize: false }
        );
    }

    placeCaret() {
        const { selection } = this.editor.shared;
        selection.focusEditable();
        selection.setCursorEnd(this.editor.editable);
    }

    /** Upload any image still held in the browser, then hand over the final Html. */
    async commit() {
        const editor = this.editor;
        if (!editor || editor.isDestroyed) {
            return;
        }
        await editor.shared.imageSave?.savePendingImages();
        if (!editor.isDestroyed) {
            this.props.onChange(editor.getContent());
        }
    }

    onKeydown(ev) {
        this.props.onKeydown(ev);
    }

    onPaste(ev) {
        this.props.onPaste?.(ev);
    }
}
