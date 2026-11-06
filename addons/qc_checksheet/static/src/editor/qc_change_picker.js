/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { useDebounced } from "@web/core/utils/timing";

const SEARCH_DEBOUNCE_MS = 250;
// A click on a result blurs the input first, so let that click land before closing.
const BLUR_CLOSE_MS = 150;

/** The Engineering Changes of a Revision: removable chips, and a box to add more. */
export class QcChangePicker extends Component {
    static template = "qc_checksheet.ChangePicker";
    static props = {
        // [{id, name, title, state_label}]
        value: Array,
        // term => [{id, name, title, state_label, affects}]
        search: Function,
        onChange: Function,
        onOpen: { type: Function, optional: true },
        readonly: { type: Boolean, optional: true },
    };

    setup() {
        this.state = useState({ term: "", results: [], open: false });
        this.request = 0;
        this.searchSoon = useDebounced(() => this.runSearch(), SEARCH_DEBOUNCE_MS);
    }

    get options() {
        const picked = new Set(this.props.value.map((change) => change.id));
        return this.state.results.filter((change) => !picked.has(change.id));
    }

    async runSearch() {
        // Only the latest search counts: a reply for older text arriving last is dropped.
        const request = ++this.request;
        const results = await this.props.search(this.state.term);
        if (request === this.request) {
            this.state.results = results;
        }
    }

    onInput(ev) {
        this.state.term = ev.target.value;
        this.state.open = true;
        this.searchSoon();
    }

    onFocus() {
        this.state.open = true;
        this.searchSoon();
    }

    onBlur() {
        setTimeout(() => {
            this.state.open = false;
            this.state.term = "";
        }, BLUR_CLOSE_MS);
    }

    add(change) {
        this.state.term = "";
        this.state.open = false;
        this.props.onChange([...this.props.value, change]);
    }

    remove(change) {
        this.props.onChange(this.props.value.filter((other) => other.id !== change.id));
    }
}
