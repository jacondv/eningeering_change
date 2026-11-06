/** @odoo-module **/

import { Component } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";

/** The check sheet's real PDF, shown in the browser's own PDF viewer. */
export class QcPreviewDialog extends Component {
    static template = "qc_checksheet.PreviewDialog";
    static components = { Dialog };
    static props = {
        close: Function,
        title: String,
        url: String,
        onPrint: Function,
    };

    print() {
        this.props.close();
        this.props.onPrint();
    }
}
