/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { QcChangePicker } from "./qc_change_picker";

/** New Revision: why it changes, and the Engineering Changes behind it, if any. */
export class QcNewRevisionDialog extends Component {
    static template = "qc_checksheet.NewRevisionDialog";
    static components = { Dialog, QcChangePicker };
    static props = {
        close: Function,
        search: Function,
        onConfirm: Function,
    };

    setup() {
        this.state = useState({ reason: "", changes: [], creating: false });
    }

    get isBlocked() {
        return this.state.creating || !this.state.reason.trim();
    }

    setChanges(changes) {
        this.state.changes = changes;
    }

    async create() {
        if (this.isBlocked) {
            return;
        }
        this.state.creating = true;
        try {
            await this.props.onConfirm(this.state.reason.trim(), this.state.changes);
            this.props.close();
        } finally {
            this.state.creating = false;
        }
    }
}
