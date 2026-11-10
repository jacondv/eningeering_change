/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";

/**
 * Approving a Revision change of a Job that already has a signed scan: the Approver says whether the
 * Job must be inspected again on the new Revision, or why it needn't be.
 */
export class QcApproveDialog extends Component {
    static template = "qc_checksheet.ApproveDialog";
    static components = { Dialog };
    static props = {
        close: Function,
        typeName: String,
        // Revision numbers and the scan, for the sentence at the top.
        fromRevision: Number,
        toRevision: Number,
        scanText: String,
        onConfirm: Function,
    };

    setup() {
        this.state = useState({ decision: "required", reason: "", saving: false });
    }

    get isBlocked() {
        return this.state.saving || (this.state.decision === "skipped" && !this.state.reason.trim());
    }

    async confirm() {
        if (this.isBlocked) {
            return;
        }
        this.state.saving = true;
        try {
            await this.props.onConfirm(this.state.decision, this.state.reason.trim());
            this.props.close();
        } finally {
            this.state.saving = false;
        }
    }
}
