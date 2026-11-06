/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { download } from "@web/core/network/download";

/** Pick a Job's sheets to print: one PDF each (in a ZIP), or one combined PDF. */
export class QcPrintAllDialog extends Component {
    static template = "qc_checksheet.PrintAllDialog";
    static components = { Dialog };
    static props = {
        close: Function,
        jobName: String,
        // The Job QC page's rows that have a sheet.
        rows: Array,
    };

    setup() {
        this.state = useState({
            // Released sheets are ticked; one never Released yet can still be printed as it stands.
            rows: this.props.rows.map((row) => ({ ...row, selected: row.current.state === "released" })),
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
            await download({
                url: "/qc_checksheet/print_all",
                data: {
                    ids: rows.map((row) => row.current.id).join(","),
                    combined: this.state.combined ? "1" : "0",
                },
            });
            this.props.close();
        } finally {
            this.state.printing = false;
        }
    }
}
