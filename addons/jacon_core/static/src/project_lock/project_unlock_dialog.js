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

    onKeydown(ev) {
        if (ev.key !== "Enter") {
            return;
        }
        // preventDefault() blocks any native default behavior the browser
        // might attach to Enter on this input (autofill submission, etc.);
        // the `checking` guard in confirm() below stops a second call from
        // re-entering mid-flight if Enter still manages to fire twice -
        // together these were producing a spurious "Incorrect password"
        // instead of unlocking on Enter, even with the right password.
        ev.preventDefault();
        this.confirm();
    }

    async confirm() {
        if (!this.state.password || this.state.checking) {
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
