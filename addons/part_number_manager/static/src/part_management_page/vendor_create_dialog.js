/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";

// Quick "Create Vendor" from the Create/Convert page's Vendor field. A
// Vendor needs a Name or a Code - either one is enough. Duplicate checks run
// on the server (res.partner.pnm_create_vendor): a Code already in use
// blocks creation and offers that Vendor instead (Vendor Code is unique); an
// identical Name only asks for confirmation.
export class VendorCreateDialog extends Component {
    static template = "part_number_manager.VendorCreateDialog";
    static components = { Dialog };
    static props = {
        close: Function,
        initialText: { type: String, optional: true },
        onDone: Function, // ({id, label}) => void - created or picked Vendor
    };

    setup() {
        this.orm = useService("orm");
        const text = (this.props.initialText || "").trim();
        // Digits-only text is almost certainly a Vendor Code, anything else a name.
        const looksLikeCode = /^\d+$/.test(text);
        this.state = useState({
            name: looksLikeCode ? "" : text,
            code: looksLikeCode ? text : "",
            error: "",
            existing: null, // {status, vendor} returned by the server when it needs a decision
            saving: false,
        });
    }

    get canCreate() {
        return !this.state.saving && !!(this.state.name.trim() || this.state.code.trim());
    }

    onInput() {
        this.state.error = "";
        this.state.existing = null;
    }

    async onCreate(allowSameName = false) {
        if (!this.canCreate) {
            this.state.error = "Enter a Vendor Name or a Vendor Code.";
            return;
        }
        this.state.saving = true;
        try {
            const result = await this.orm.call("res.partner", "pnm_create_vendor", [
                this.state.name, this.state.code, allowSameName,
            ]);
            if (result.status === "created") {
                this._done(result.vendor);
            } else if (result.status === "missing") {
                this.state.error = "Enter a Vendor Name or a Vendor Code.";
            } else {
                this.state.existing = result;
            }
        } finally {
            this.state.saving = false;
        }
    }

    onUseExisting() {
        this._done(this.state.existing.vendor);
    }

    _done(vendor) {
        this.props.onDone(vendor);
        this.props.close();
    }
}
