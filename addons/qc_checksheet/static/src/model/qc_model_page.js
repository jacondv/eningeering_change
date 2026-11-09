/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
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
        this.modelId = this.props.action.context?.active_id;
        this.state = useState({ model: null });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.model = await this.orm.call(CHECKSHEET_MODEL, "model_overview", [this.modelId]);
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
                // One new sheet: straight to writing it.
                if (created.length === 1) {
                    await this.open({ id: created[0].id, layout: created[0].layout });
                } else {
                    await this.load();
                }
            },
        });
    }
}

registry.category("actions").add("qc_checksheet.model", QcModelPage);
