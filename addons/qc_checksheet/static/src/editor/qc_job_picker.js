/** @odoo-module **/

import { Component, onWillUpdateProps, useState } from "@odoo/owl";
import { useDebounced } from "@web/core/utils/timing";

const SEARCH_DEBOUNCE_MS = 250;
// A click on a result blurs the input first, so let that click land before closing.
const BLUR_CLOSE_MS = 150;

/** A Job search box with a dropdown of matches, as used on the New page. */
export class QcJobPicker extends Component {
    static template = "qc_checksheet.JobPicker";
    static props = {
        // The Job picked ({id, name, model}), or null.
        value: { optional: true },
        search: Function,
        onPick: Function,
        inputId: { type: String, optional: true },
        placeholder: { type: String, optional: true },
        emptyText: { type: String, optional: true },
        // Small, with a button to clear the choice.
        clearable: { type: Boolean, optional: true },
    };

    setup() {
        this.state = useState({ term: this.props.value?.name || "", results: [], open: false });
        this.request = 0;
        this.searchSoon = useDebounced(() => this.runSearch(), SEARCH_DEBOUNCE_MS);
        // The page may change the choice itself, e.g. clear it when the Type changes.
        onWillUpdateProps((next) => {
            if (next.value !== this.props.value) {
                this.state.term = next.value?.name || "";
            }
        });
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
            this.state.term = this.props.value?.name || "";
        }, BLUR_CLOSE_MS);
    }

    pick(job) {
        this.state.term = job?.name || "";
        this.state.open = false;
        this.props.onPick(job);
    }
}
