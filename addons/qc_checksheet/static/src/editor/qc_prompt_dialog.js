/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";

/**
 * A question with its own buttons and, with `inputLabel`, a required one-line
 * answer (the reason for a Reject or a New Revision).
 */
export class QcPromptDialog extends Component {
    static template = "qc_checksheet.PromptDialog";
    static components = { Dialog };
    static props = {
        close: Function,
        title: String,
        body: { type: String, optional: true },
        inputLabel: { type: String, optional: true },
        buttons: Array,
        onDismiss: { type: Function, optional: true },
    };

    setup() {
        this.state = useState({ text: "" });
    }

    get isBlocked() {
        return !!this.props.inputLabel && !this.state.text.trim();
    }

    choose(button) {
        if (button.needsInput !== false && this.isBlocked) {
            return;
        }
        this.props.close();
        button.onClick(this.state.text.trim());
    }

    dismiss() {
        this.props.close();
        this.props.onDismiss?.();
    }
}
