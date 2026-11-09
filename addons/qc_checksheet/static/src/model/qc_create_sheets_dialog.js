/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";

const CHECKSHEET_MODEL = "qc.checksheet";

/** One row per Type to create: what to start from, and its Header. */
export class QcCreateSheetsDialog extends Component {
    static template = "qc_checksheet.CreateSheetsDialog";
    static components = { Dialog };
    static props = {
        close: Function,
        modelId: Number,
        modelName: String,
        typeIds: Array,
        onCreated: Function,
    };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = useState({ rows: [], creating: false });
        onWillStart(async () => {
            const rows = await this.orm.call(CHECKSHEET_MODEL, "model_sheet_sources", [
                this.props.modelId,
                this.props.typeIds,
            ]);
            this.state.rows = rows.map((row) => ({ ...row, selected: true }));
        });
    }

    get selectedRows() {
        return this.state.rows.filter((row) => row.selected);
    }

    get cannotCreate() {
        const rows = this.selectedRows;
        return this.state.creating || !rows.length || rows.some((row) => !row.header.trim());
    }

    sameTypeOptions(row) {
        return row.options.filter((option) => option.same_type);
    }

    otherTypeOptions(row) {
        return row.options.filter((option) => !option.same_type);
    }

    onSourceChange(row, ev) {
        row.source_id = parseInt(ev.target.value) || false;
    }

    async create() {
        if (this.cannotCreate) {
            return;
        }
        this.state.creating = true;
        try {
            const created = await this.orm.call(CHECKSHEET_MODEL, "model_create_sheets", [
                this.props.modelId,
                this.selectedRows.map((row) => ({
                    type_id: row.type_id,
                    header: row.header.trim(),
                    source_id: row.source_id,
                })),
            ]);
            this.notification.add(`${created.length} check sheet(s) created as Draft Rev 0`, { type: "success" });
            this.props.close();
            await this.props.onCreated(created);
        } finally {
            this.state.creating = false;
        }
    }
}
