/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";
import { QcJobPicker } from "../editor/qc_job_picker";

const CHECKSHEET_MODEL = "qc.checksheet";
// The highest Revision a sheet may start at (MAX_START_REVISION on the server).
const MAX_START_REV = 99;

/**
 * Set up the sheet of each Type a Model is missing. For each, one of two ways:
 *  - use the sheet of another Model (JSV6-EMU-A-068 uses that of JSV6-EMU-A): nothing is written, and the Model
 *    whose name this one extends is chosen when there is one;
 *  - create a new sheet of its own: blank, or copied from the sheet of a Model of the same Type (found by typing
 *    its name), at Rev 0 or at the Revision it already has elsewhere (Word, say).
 * A sheet of another Type is never offered to copy, whatever it looks like.
 */
export class QcCreateSheetsDialog extends Component {
    static template = "qc_checksheet.CreateSheetsDialog";
    static components = { Dialog, QcJobPicker };
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
            this.state.rows = rows.map((row) => ({
                ...row,
                selected: true,
                // The Model to copy from, picked by typing its name: none is chosen behind the user's back, so a
                // new sheet starts blank.
                copy_model: false,
                // The Model proposed from the name, to say why it was chosen.
                suggested_id: row.share_model ? row.share_model.id : false,
                // "share": use another Model's sheet; "new": write one. Sharing first when a Model is suggested.
                mode: row.share_model ? "share" : "new",
                // start_rev is kept as typed: the field can be empty while typing.
                start_rev: "0",
            }));
        });
    }

    get selectedRows() {
        return this.state.rows.filter((row) => row.selected);
    }

    get severalTypes() {
        return this.state.rows.length > 1;
    }

    startRevOk(row) {
        const value = String(row.start_rev).trim();
        return /^\d{1,2}$/.test(value) && Number(value) <= MAX_START_REV;
    }

    /** A sheet that already has Revisions on paper: its earlier ones go into the Revision History. */
    startsAbove0(row) {
        return Number(row.start_rev) > 0;
    }

    /** What still stops this row: a Model to use, or the Header and Revision of a new sheet. */
    rowIncomplete(row) {
        if (row.mode === "share") {
            return !row.share_model;
        }
        return !row.header.trim() || !this.startRevOk(row);
    }

    get cannotCreate() {
        const rows = this.selectedRows;
        return this.state.creating || !rows.length || rows.some((row) => this.rowIncomplete(row));
    }

    get confirmLabel() {
        const rows = this.selectedRows;
        if (rows.length && rows.every((row) => row.mode === "share")) {
            return rows.length === 1 ? "Use this sheet" : `Use ${rows.length} sheets`;
        }
        if (rows.every((row) => row.mode === "new")) {
            return rows.length === 1 ? "Create the sheet" : `Create ${rows.length} sheets`;
        }
        return `Set up ${rows.length} sheets`;
    }

    /** Search for the Models that have a sheet of this row's Type to use, or a Released one to copy. */
    searchShare(row) {
        return (term) => this.orm.call(CHECKSHEET_MODEL, "model_share_sources", [row.type_id, this.props.modelId, term]);
    }

    searchCopy(row) {
        return (term) => this.orm.call(CHECKSHEET_MODEL, "model_copy_sources", [row.type_id, this.props.modelId, term]);
    }

    setMode(row, mode) {
        row.mode = mode;
    }

    pickShare(row, model) {
        row.share_model = model || false;
    }

    pickCopy(row, model) {
        row.copy_model = model || false;
    }

    async create() {
        if (this.cannotCreate) {
            return;
        }
        this.state.creating = true;
        try {
            const created = await this.orm.call(CHECKSHEET_MODEL, "model_create_sheets", [
                this.props.modelId,
                this.selectedRows.map((row) =>
                    row.mode === "share"
                        ? { type_id: row.type_id, share_model_id: row.share_model.id }
                        : {
                              type_id: row.type_id,
                              header: row.header.trim(),
                              source_model_id: row.copy_model ? row.copy_model.id : false,
                              start_rev: Number(row.start_rev),
                          }
                ),
            ]);
            const shared = created.filter((item) => !item.id).length;
            this.notification.add(
                shared === created.length
                    ? `${shared} sheet(s) shared from another Model`
                    : `${created.length - shared} check sheet(s) created as Draft` + (shared ? `, ${shared} shared` : ""),
                { type: "success" }
            );
            this.props.close();
            await this.props.onCreated(created);
        } finally {
            this.state.creating = false;
        }
    }
}
