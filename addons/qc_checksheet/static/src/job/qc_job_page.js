/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { QcCreateSheetsDialog } from "./qc_create_sheets_dialog";

const CHECKSHEET_MODEL = "qc.checksheet";

/** Every check sheet of one Job, by Type. Its context's active_id is the Job. */
export class QcJobPage extends Component {
    static template = "qc_checksheet.JobPage";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.dialog = useService("dialog");
        this.jobId = this.props.action.context?.active_id;
        this.state = useState({ job: null });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.job = await this.orm.call(CHECKSHEET_MODEL, "job_overview", [this.jobId]);
    }

    get job() {
        return this.state.job;
    }

    get missingRows() {
        return this.job.rows.filter((row) => row.required && !row.current);
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

    print(sheet) {
        return this.action.doAction("qc_checksheet.action_report_qc_checksheet", {
            additionalContext: { active_ids: [sheet.id], active_model: CHECKSHEET_MODEL },
        });
    }

    openJobForm() {
        return this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "project.project",
            res_id: this.jobId,
            views: [[false, "form"]],
        });
    }

    create(rows) {
        this.dialog.add(QcCreateSheetsDialog, {
            jobId: this.jobId,
            jobName: this.job.name,
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

registry.category("actions").add("qc_checksheet.job", QcJobPage);
