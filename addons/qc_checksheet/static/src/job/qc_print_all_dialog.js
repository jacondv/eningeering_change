/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { download } from "@web/core/network/download";

/**
 * Pick a Job's sheets to print: one PDF each (in a ZIP), or one combined PDF.
 * Printing pins the Revision of any sheet the Job prints for the first time.
 */
export class QcPrintAllDialog extends Component {
    static template = "qc_checksheet.PrintAllDialog";
    static components = { Dialog };
    static props = {
        close: Function,
        jobName: String,
        // The Job QC page's rows that have something to print, with `sheet` the Revision printed.
        rows: Array,
        // Pins the rows' Revisions and returns the Job's own sheet ids.
        pin: Function,
    };

    setup() {
        this.state = useState({
            rows: this.props.rows.map((row) => ({ ...row, selected: true })),
            combined: false,
            printing: false,
        });
    }

    get selectedRows() {
        return this.state.rows.filter((row) => row.selected);
    }

    async print() {
        const rows = this.selectedRows;
        if (!rows.length || this.state.printing) {
            return;
        }
        this.state.printing = true;
        try {
            const ids = await this.props.pin(rows);
            await download({
                url: "/qc_checksheet/print_all",
                data: {
                    ids: ids.join(","),
                    combined: this.state.combined ? "1" : "0",
                },
            });
            this.props.close();
        } finally {
            this.state.printing = false;
        }
    }
}
