import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";

export class ProjectUnlockDialog extends Component {
    static template = "jacon_core.ProjectUnlockDialog";
    static components = { Dialog };
    static props = {
        close: Function,
        onConfirm: Function,
    };

    setup() {
        this.title = _t("Enter your password to edit this Project");
        this.state = useState({ password: "", error: "", checking: false });
    }

    async confirm() {
        if (!this.state.password) {
            return;
        }
        this.state.checking = true;
        this.state.error = "";
        const ok = await this.props.onConfirm(this.state.password);
        this.state.checking = false;
        if (ok) {
            this.props.close();
        } else {
            this.state.error = _t("Incorrect password.");
        }
    }
}
