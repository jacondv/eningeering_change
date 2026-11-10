/** @odoo-module **/

import { Component, onMounted, onWillStart, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { deserializeDate, deserializeDateTime, formatDateTime } from "@web/core/l10n/dates";
import { QcPromptDialog } from "../editor/qc_prompt_dialog";
import { QcCreateSheetsDialog } from "../model/qc_create_sheets_dialog";
import { QcApproveDialog } from "./qc_approve_dialog";
import { QcScanDialog } from "./qc_scan_dialog";
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
        this.page = useRef("page");
        // Coming from a list or the Dashboard: the Type whose row to show, and whether to open its upload at once.
        this.focusTypeId = this.props.action.context?.focus_type_id || false;
        this.focusUpload = !!this.props.action.context?.focus_upload;
        // openScans: the Types whose earlier scans are unfolded. focused: the row being pointed at.
        this.state = useState({ job: null, printing: false, openScans: {}, focused: this.focusTypeId });
        onWillStart(() => this.load());
        onMounted(() => this.applyFocus());
    }

    /** Scrolls to the row the user came for, and opens the scan upload when that is what they asked. */
    applyFocus() {
        if (!this.focusTypeId) {
            return;
        }
        const row = this.job.rows.find((candidate) => candidate.type_id === this.focusTypeId);
        const element = this.page.el?.querySelector(`[data-type-id="${this.focusTypeId}"]`);
        element?.scrollIntoView({ block: "center" });
        if (row && this.focusUpload && row.pinned && row.inspection?.can_upload) {
            this.upload(row);
        }
        this.focusUpload = false;
    }

    /**
     * What the row offers, always in the same order so every row reads alike: Print, Upload scan, Update/Change
     * Rev, Choose Rev, then the links to look. The buttons all look alike, grey.
     * Each: {key, label, css, title, disabled, run}
     */
    actions(row) {
        const sheet = this.printed(row);
        if (!sheet) {
            return [];
        }
        const inspection = row.inspection;
        const upload = {
            key: "upload",
            label: "Upload scan",
            title: "Upload the signed scan of this sheet",
            run: () => this.upload(row),
        };
        const print = {
            key: "print",
            label: "Print",
            disabled: this.state.printing,
            run: () => this.print(row),
        };
        const list = [];
        // Same place in every row, so the eye finds a button where it was in the row above.
        list.push({ ...print, css: "btn-secondary" });
        if (inspection?.can_upload) {
            list.push({ ...upload, css: "btn-secondary" });
        }
        if (row.update) {
            list.push({
                key: "update",
                label: row.outdated ? "Update Rev" : "Change Rev",
                title: "An Approver has to approve the change",
                css: "btn-secondary",
                run: () => this.update(row),
            });
        }
        if (row.choosable) {
            list.push({
                key: "choose",
                label: "Choose Rev",
                title: "Pin another Revision than the current one",
                css: "btn-secondary",
                run: () => this.choose(row),
            });
        }
        list.push({ key: "open", label: "Open", title: "Read the sheet", css: "btn-link", run: () => this.open(sheet) });
        if (row.pinned) {
            list.push({
                key: "details",
                label: "Details",
                title: "Check Date and the history of this Job's sheet",
                css: "btn-link",
                run: () => this.openJobSheet(row),
            });
        }
        return list;
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

    /** A day as 12-Aug-2025, the way the PDF prints it. */
    formatDay(value) {
        return value ? deserializeDate(value).toFormat("dd-MMM-yyyy") : "";
    }

    // Scans

    toggleScans(row) {
        this.state.openScans[row.type_id] = !this.state.openScans[row.type_id];
    }

    upload(row) {
        this.dialog.add(QcScanDialog, {
            jobSheetId: row.pinned.job_sheet_id,
            typeName: row.type_name,
            revision: row.pinned.revision,
            limits: this.job.scan_limits,
            onUploaded: () => this.load(),
        });
    }

    /** Only a QC Administrator may: the scan is a signed record. */
    deleteScan(scan) {
        this.dialog.add(QcPromptDialog, {
            title: "Delete this scan?",
            body: `Rev ${scan.revision}, checked ${this.formatDay(scan.check_date)}, ${scan.files.length} file(s). The files are deleted with it.`,
            buttons: [
                {
                    label: "Delete",
                    primary: true,
                    needsInput: false,
                    onClick: async () => {
                        await this.orm.unlink("qc.job.checksheet.scan", [scan.id]);
                        await this.load();
                    },
                },
                { label: "Cancel", needsInput: false, onClick: () => {} },
            ],
        });
    }

    /** What the Approver and the one asking for a change are told about the scan the Job already has. */
    scanText(row) {
        const [latest] = row.inspection?.scans || [];
        return latest ? `It was inspected on Rev ${latest.revision}, checked ${this.formatDay(latest.check_date)}.` : "";
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
            // A Job already inspected: whoever asks, and whoever approves, knows it may need inspecting again.
            scanWarning: row.inspection?.scans.length
                ? `${this.scanText(row)} After the change it may need a new inspection: the Approver decides.`
                : "",
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

    /** A Job with a scan: the Approver says first whether it must be inspected again. */
    async approve(row) {
        if (!row.pending.has_scan) {
            await this.orm.call(CHANGE_MODEL, "action_approve", [[row.pending.id]]);
            await this.load();
            return;
        }
        this.dialog.add(QcApproveDialog, {
            typeName: row.type_name,
            fromRevision: row.pinned.revision,
            toRevision: row.pending.revision,
            scanText: this.scanText(row),
            onConfirm: async (decision, reason) => {
                await this.orm.call(CHANGE_MODEL, "action_approve", [[row.pending.id], decision, reason]);
                await this.load();
            },
        });
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

    /** The Model has no sheet of this Type yet: set it up here, without going to the Model's page first. */
    createSheet(row) {
        this.dialog.add(QcCreateSheetsDialog, {
            modelId: this.job.model_id,
            modelName: this.job.model,
            typeIds: [row.type_id],
            onCreated: async (created) => {
                // A sheet written here is opened to be written; one that is only used from another Model, not.
                if (created.length === 1 && created[0].id) {
                    await this.open({ id: created[0].id, layout: created[0].layout });
                } else {
                    await this.load();
                }
            },
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
