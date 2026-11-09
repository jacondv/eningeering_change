/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";

/**
 * Which issued Revision of its Model's sheet a Job prints: an older one too,
 * with a reason. In "choose" mode the Job hasn't printed the sheet yet and is
 * pinned at once; in "change" mode it prints one already, and an Approver has
 * to approve the move.
 */
export class QcUpdateRevisionDialog extends Component {
    static template = "qc_checksheet.UpdateRevisionDialog";
    static components = { Dialog };
    static props = {
        close: Function,
        typeName: String,
        mode: { type: String, optional: true },
        // {id, revision, state, state_label, reason, changes, pinned, current}, newest first.
        options: Array,
        onConfirm: Function,
    };

    setup() {
        // Changing: the current Revision when the Job isn't on it. Choosing: the newest one that is not the
        // current Revision, since printing would take that one anyway.
        const first = this.isChoosing
            ? this.props.options.find((option) => !option.current) || this.props.options[0]
            : this.props.options.find((option) => option.current && !option.pinned)
              || this.props.options.find((option) => !option.pinned);
        this.state = useState({ revisionId: first ? first.id : false, reason: "", saving: false });
    }

    get isChoosing() {
        return this.props.mode === "choose";
    }

    /** What an older Revision is compared with: what the Job prints, or else the Model's current one. */
    get reference() {
        return this.props.options.find((option) => option.pinned)
            || this.props.options.find((option) => option.current);
    }

    get picked() {
        return this.props.options.find((option) => option.id === this.state.revisionId);
    }

    get isOlder() {
        return !!(this.picked && this.reference && this.picked.revision < this.reference.revision);
    }

    get isBlocked() {
        return this.state.saving || !this.picked || !this.state.reason.trim();
    }

    pick(option) {
        if (!option.pinned) {
            this.state.revisionId = option.id;
        }
    }

    async confirm() {
        if (this.isBlocked) {
            return;
        }
        this.state.saving = true;
        try {
            await this.props.onConfirm(this.state.revisionId, this.state.reason.trim());
            this.props.close();
        } finally {
            this.state.saving = false;
        }
    }
}
