/** @odoo-module **/

import { Component, markup } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";

/** Quick look at what's on screen, including changes that aren't saved yet. */
export class QcPreviewDialog extends Component {
    static template = "qc_checksheet.PreviewDialog";
    static components = { Dialog };
    static props = {
        close: Function,
        sheet: Object,
        groups: Array,
        stamp: String,
        onPrint: Function,
    };

    html(value) {
        return markup(value || "");
    }

    print() {
        this.props.close();
        this.props.onPrint();
    }
}
