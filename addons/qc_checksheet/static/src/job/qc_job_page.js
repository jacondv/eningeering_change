/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { deserializeDateTime, formatDateTime } from "@web/core/l10n/dates";
import { QcPromptDialog } from "../editor/qc_prompt_dialog";
import { QcUpdateRevisionDialog } from "./qc_update_revision_dialog";
import { QcPrintAllDialog } from "./qc_print_all_dialog";

const JOB_SHEET_MODEL = "qc.job.checksheet";
const CHANGE_MODEL = "qc.job.checksheet.change";

/**
 * The check sheets one Job prints, by Type. The first print of a Type pins
 * the Model's Released Revision of that moment; the Job keeps it until it is
 * updated. Its context's active_id is the Job.
 */
export class QcJobPage extends Component {
    static template = "qc_checksheet.JobPage";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.action = useService("action");
        this.dialog = useService("dialog");
        this.jobId = this.props.action.context?.active_id;
        this.state = useState({ job: null, printing: false });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.job = await this.orm.call(JOB_SHEET_MODEL, "job_overview", [this.jobId]);
    }

    get job() {
        return this.state.job;
    }

    /** What the row prints: the pinned Revision, or else the Model's current one. */
    printed(row) {
        return row.pinned || row.current;
    }

    get printableRows() {
        return this.job.rows.filter((row) => this.printed(row));
    }

    badgeClass(sheet) {
        return `o_qce_badge o_qce_badge_${sheet.state}`;
    }

    formatDateTime(value) {
        return value ? formatDateTime(deserializeDateTime(value)) : "";
    }

    /** Pin what isn't pinned yet; returns the Job's own sheet ids, in the order asked. */
    async pin(rows) {
        const ids = await this.orm.call(JOB_SHEET_MODEL, "job_print", [
            this.jobId,
            rows.map((row) => row.type_id),
        ]);
        await this.load();
        return ids;
    }

    async print(row) {
        if (this.state.printing) {
            return;
        }
        this.state.printing = true;
        try {
            const ids = await this.pin([row]);
            await this.action.doAction("qc_checksheet.action_report_qc_job_checksheet", {
                additionalContext: { active_ids: ids, active_model: JOB_SHEET_MODEL },
            });
        } finally {
            this.state.printing = false;
        }
    }

    printAll() {
        this.dialog.add(QcPrintAllDialog, {
            jobName: this.job.name,
            rows: this.printableRows.map((row) => ({ ...row, sheet: this.printed(row) })),
            pin: (rows) => this.pin(rows),
        });
    }

    options(row) {
        return this.orm.call(JOB_SHEET_MODEL, "job_options", [this.jobId, row.type_id]);
    }

    /** Ask to move this Job to another issued Revision, an older one too: an Approver has to approve. */
    async update(row) {
        const options = await this.options(row);
        this.dialog.add(QcUpdateRevisionDialog, {
            typeName: row.type_name,
            mode: "change",
            options,
            onConfirm: async (revisionId, reason) => {
                await this.orm.call(JOB_SHEET_MODEL, "action_request_change", [
                    [row.pinned.job_sheet_id],
                    reason,
                    revisionId,
                ]);
                this.notification.add("Change requested. It waits for an Approver.", { type: "success" });
                await this.load();
            },
        });
    }

    /** First pinning to a Revision other than the current one: done at once, no approval. */
    async choose(row) {
        const options = await this.options(row);
        this.dialog.add(QcUpdateRevisionDialog, {
            typeName: row.type_name,
            mode: "choose",
            options,
            onConfirm: async (revisionId, reason) => {
                await this.orm.call(JOB_SHEET_MODEL, "job_pin", [this.jobId, row.type_id, revisionId, reason]);
                await this.load();
            },
        });
    }

    async approve(row) {
        await this.orm.call(CHANGE_MODEL, "action_approve", [[row.pending.id]]);
        await this.load();
    }

    reject(row) {
        this.dialog.add(QcPromptDialog, {
            title: `Reject the change of ${row.type_name} to Rev ${row.pending.revision}`,
            inputLabel: "Reason for rejecting",
            buttons: [
                {
                    label: "Reject",
                    primary: true,
                    onClick: async (reason) => {
                        await this.orm.call(CHANGE_MODEL, "action_reject", [[row.pending.id], reason]);
                        await this.load();
                    },
                },
                { label: "Cancel", needsInput: false, onClick: () => {} },
            ],
        });
    }

    async cancelRequest(row) {
        await this.orm.call(CHANGE_MODEL, "action_cancel", [[row.pending.id]]);
        await this.load();
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
            res_model: "qc.checksheet",
            res_id: sheet.id,
            views: [[false, "form"]],
        });
    }

    openJobSheet(row) {
        return this.action.doAction({
            type: "ir.actions.act_window",
            res_model: JOB_SHEET_MODEL,
            res_id: row.pinned.job_sheet_id,
            views: [[false, "form"]],
        });
    }

    openModel() {
        return this.action.doAction({
            type: "ir.actions.client",
            tag: "qc_checksheet.model",
            name: `QC: ${this.job.model}`,
            context: { active_id: this.job.model_id },
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

    openJobForm() {
        return this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "project.project",
            res_id: this.jobId,
            views: [[false, "form"]],
        });
    }
}

registry.category("actions").add("qc_checksheet.job", QcJobPage);
