/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { Chatter } from "@mail/chatter/web_portal/chatter";
import { browser } from "@web/core/browser/browser";

// The same key as the chatter of the forms (jacon_core): fold it away on a form, and it is folded here too.
const STORAGE_KEY = "jacon_core.chatter_collapsed";

/**
 * The chatter of a record (a Job, a Model) beside a QC page, laid out like the one of a form: a thin handle to fold
 * it away, whose state is kept in this browser.
 */
export class QcChatterPanel extends Component {
    static template = "qc_checksheet.ChatterPanel";
    static components = { Chatter };
    static props = {
        threadModel: String,
        threadId: Number,
    };

    setup() {
        let collapsed = false;
        try {
            collapsed = browser.localStorage.getItem(STORAGE_KEY) === "1";
        } catch {
            // Storage can be blocked: open, as by default.
        }
        this.state = useState({ collapsed });
    }

    toggle() {
        this.state.collapsed = !this.state.collapsed;
        try {
            if (this.state.collapsed) {
                browser.localStorage.setItem(STORAGE_KEY, "1");
            } else {
                browser.localStorage.removeItem(STORAGE_KEY);
            }
        } catch {
            // Not kept: the next page opens it again.
        }
    }
}
