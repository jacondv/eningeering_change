/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { QcCreateSheetsDialog } from "./qc_create_sheets_dialog";

const CHECKSHEET_MODEL = "qc.checksheet";

/**
 * Every check sheet of one Model, by Type: where sheets are written and
 * revised. Its context's active_id is the Model (equipment.model).
 */
export class QcModelPage extends Component {
    static template = "qc_checksheet.ModelPage";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.modelId = this.props.action.context?.active_id;
        this.state = useState({ model: null, selected: [] });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.model = await this.orm.call(CHECKSHEET_MODEL, "model_overview", [this.modelId]);
        // Only Types that still have a sheet stay selected.
        const present = new Set(this.selectableRows.map((row) => row.type_id));
        this.state.selected = this.state.selected.filter((typeId) => present.has(typeId));
    }

    // Choosing sheets to take away

    /** The rows with a sheet, own or used from another Model. */
    get selectableRows() {
        return this.model.can_share ? this.model.rows.filter((row) => row.current) : [];
    }

    get allSelected() {
        return this.selectableRows.length > 0 && this.selectableRows.every((row) => this.state.selected.includes(row.type_id));
    }

    toggle(row) {
        const index = this.state.selected.indexOf(row.type_id);
        if (index >= 0) {
            this.state.selected.splice(index, 1);
        } else {
            this.state.selected.push(row.type_id);
        }
    }

    toggleAll() {
        this.state.selected = this.allSelected ? [] : this.selectableRows.map((row) => row.type_id);
    }

    clearSelection() {
        this.state.selected = [];
    }

    /** Takes the chosen sheets away from the Model, to set them up again with Create: that is how one is changed. */
    deleteSelected() {
        const rows = this.model.rows.filter((row) => this.state.selected.includes(row.type_id));
        const lines = rows.map((row) =>
            row.shared_from
                ? `${row.type_name}: only the link to the sheet of ${row.shared_from.name} is removed`
                : `${row.type_name}: the sheet and all its Revisions are deleted`
        );
        this.dialog.add(ConfirmationDialog, {
            title: `Delete ${rows.length} check sheet(s) of ${this.model.name}`,
            body:
                `${lines.join(". ")}. ` +
                "A sheet a Job has printed, or that another Model uses, can't be deleted. " +
                "Set it up again afterwards with Create.",
            confirmLabel: "Delete",
            confirm: async () => {
                await this.orm.call(CHECKSHEET_MODEL, "model_delete_sheets", [this.modelId, rows.map((row) => row.type_id)]);
                this.state.selected = [];
                await this.load();
            },
            cancel: () => {},
        });
    }

    get model() {
        return this.state.model;
    }

    get missingRows() {
        return this.model.rows.filter((row) => row.required && !row.current);
    }

    badgeClass(sheet) {
        return `o_qce_badge o_qce_badge_${sheet.state}`;
    }

    open(sheet) {
        if (sheet.layout === "standard") {
            return this.action.doAction({
                type: "ir.actions.client",
                tag: "qc_checksheet.editor",
                name: "Check Sheet",
                context: { active_id: sheet.id },
            });
        }
        return this.action.doAction({
            type: "ir.actions.act_window",
            res_model: CHECKSHEET_MODEL,
            res_id: sheet.id,
            views: [[false, "form"]],
        });
    }

    /** The Model's sheet, blank: no Job details. */
    print(sheet) {
        return this.action.doAction("qc_checksheet.action_report_qc_checksheet", {
            additionalContext: { active_ids: [sheet.id], active_model: CHECKSHEET_MODEL },
        });
    }

    openJobs(row) {
        return this.action.doAction({
            type: "ir.actions.act_window",
            name: `Jobs using ${row.type_name}`,
            res_model: "qc.job.checksheet",
            views: [[false, "list"], [false, "form"]],
            domain: [["model_id", "=", this.modelId], ["type_id", "=", row.type_id]],
            context: { create: false, search_default_group_revision: 1 },
        });
    }

    /** Another Model's QC page, where the sheet it holds is written. */
    openModelPage(modelId) {
        return this.action.doAction({
            type: "ir.actions.client",
            tag: "qc_checksheet.model",
            name: "QC",
            context: { active_id: modelId },
        });
    }

    // Using another Model's sheet

    merge(row) {
        const other = row.same_as[0];
        this.dialog.add(ConfirmationDialog, {
            title: `Merge into the sheet of ${other.name}`,
            body:
                `The ${row.type_name} sheet of ${this.model.name} prints the same as the one of ${other.name}. ` +
                `It will be deleted, its Jobs, scans and change requests moved to the identical Revision of ${other.name}'s sheet, ` +
                `and ${this.model.name} will use that sheet from now on. This can't be undone.`,
            confirmLabel: "Merge",
            confirm: async () => {
                await this.orm.call(CHECKSHEET_MODEL, "model_merge", [this.modelId, row.type_id, other.model_id]);
                this.notification.add(`${this.model.name} now uses the ${row.type_name} sheet of ${other.name}`, { type: "success" });
                await this.load();
            },
            cancel: () => {},
        });
    }

    openChange(change) {
        return this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "engineering.change",
            res_id: change.id,
            views: [[false, "form"]],
        });
    }

    openModelForm() {
        return this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "equipment.model",
            res_id: this.modelId,
            views: [[false, "form"]],
        });
    }

    create(rows) {
        this.dialog.add(QcCreateSheetsDialog, {
            modelId: this.modelId,
            modelName: this.model.name,
            typeIds: rows.map((row) => row.type_id),
            onCreated: async (created) => {
                // One new sheet: straight to writing it. A sheet of another Model is used, not written here.
                if (created.length === 1 && created[0].id) {
                    await this.open({ id: created[0].id, layout: created[0].layout });
                } else {
                    await this.load();
                }
            },
        });
    }
}

registry.category("actions").add("qc_checksheet.model", QcModelPage);
