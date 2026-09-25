/** @odoo-module **/

import { Component, onWillStart, useEffect, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { PnmCombobox } from "@part_number_manager/part_management_page/pnm_combobox";

const JOB_EQUIPMENT_ITEM_MODEL = "hose_fitting_manager.job_equipment_item";
const PART_NUMBER_MODEL = "part_number_manager.part_number";
// Same key the Builder page uses - picking a Job on either page carries over
// to the other, since they're two views onto the same "building a Job's
// Hose & Fitting list" task.
const LAST_JOB_STORAGE_KEY = "hose_fitting_manager.builder.last_job";
const SEARCH_DEBOUNCE_MS = 250;
const SEARCH_LIMIT = 20;

const COLUMN_WIDTHS_STORAGE_KEY = "hose_fitting_manager.equipment_items.column_widths";
const DEFAULT_COLUMN_WIDTHS = {
    part: 260,
    description_en: 220,
    description_vn: 220,
    used_port: 140,
    open_port: 160,
};

export class EquipmentItemsPage extends Component {
    static template = "hose_fitting_manager.EquipmentItemsPage";
    static components = { PnmCombobox };
    // "*" keeps this permissive for the standalone client action (which the
    // action framework hands generic props like action/actionId/className) -
    // jobId/onRowsChanged are only used when Builder mounts this directly
    // (see equipment_items.xml's props.jobId checks and builder.xml).
    static props = {
        "*": true,
        jobId: { type: [Number, Boolean], optional: true },
        onRowsChanged: { type: Function, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.action = useService("action");

        this.state = useState({
            jobText: "",
            jobId: false,
            rows: [], // every Job Equipment Item already saved for state.jobId
            // New items are staged here first, whether from a paste or the
            // "+" button - nothing is written to the database until Save.
            pendingRows: [],
            newPartText: "",
            newPartId: false,
            newDescriptionEn: "",
            newDescriptionVn: "",
            partOptions: [], // live search results backing the "Add Item" Part combobox
            isSaving: false,
            columnWidths: this._loadColumnWidths(),
            // Multi-select on the already-saved rows table, for bulk delete -
            // { [row.id]: true }, same plain-object pattern as errors/drafts
            // elsewhere in this app (OWL's reactivity doesn't track Set
            // mutations the same way as object key assignment).
            selectedIds: {},
        });

        this.jobOptions = [];
        this._searchTimers = {};

        onWillStart(async () => {
            await this._loadJobs();
            if (this.props.jobId !== undefined) {
                this._syncFromPropJobId();
            } else {
                this._restoreJob();
            }
            await this._loadRows();
        });

        // Only fires in the embedded case (props.jobId set) - Builder's own
        // Job picker changing should reload this panel's list without a
        // remount. In the standalone case props.jobId is always undefined,
        // so this never runs (the effect's own guard below is redundant
        // with that, but kept explicit for clarity).
        useEffect(
            () => {
                if (this.props.jobId !== undefined) {
                    this._syncFromPropJobId();
                    this._loadRows();
                }
            },
            () => [this.props.jobId]
        );
    }

    // Embedded mode only: Builder owns the Job selection (and its own
    // localStorage persistence) - this panel just mirrors props.jobId,
    // resolving a label from the Job list already loaded by _loadJobs().
    _syncFromPropJobId() {
        this.state.jobId = this.props.jobId;
        const opt = this.jobOptions.find((o) => o.id === this.props.jobId);
        this.state.jobText = opt ? opt.label : "";
    }

    async _loadJobs() {
        const jobs = await this.orm.searchRead("project.project", [], ["name"]);
        this.jobOptions = jobs.filter((j) => j.name).map((j) => ({ id: j.id, label: j.name }));
    }

    // A Job passed in via context (navigated here from the Create List
    // page's "Manage Items" button) always wins over whatever Job was last
    // remembered - an explicit navigation is a stronger signal than history.
    _restoreJob() {
        const ctxJobId = this.props.action?.context?.default_job_number;
        if (ctxJobId) {
            const opt = this.jobOptions.find((o) => o.id === ctxJobId);
            if (opt) {
                this.state.jobId = opt.id;
                this.state.jobText = opt.label;
                this._saveJob();
                return;
            }
        }
        let saved = null;
        try {
            saved = JSON.parse(localStorage.getItem(LAST_JOB_STORAGE_KEY) || "null");
        } catch {
            saved = null;
        }
        if (saved && this.jobOptions.some((o) => o.id === saved.id)) {
            this.state.jobId = saved.id;
            this.state.jobText = saved.label;
        }
    }

    _saveJob() {
        try {
            if (this.state.jobId) {
                localStorage.setItem(
                    LAST_JOB_STORAGE_KEY,
                    JSON.stringify({ id: this.state.jobId, label: this.state.jobText })
                );
            }
        } catch {
            // storage unavailable - nothing else depends on it
        }
    }

    resolveIdByLabel(options, text) {
        const norm = (text || "").trim().toLowerCase();
        if (!norm) {
            return false;
        }
        const match = options.find((o) => String(o.label || "").toLowerCase() === norm);
        return match ? match.id : false;
    }

    async onJobInput(text) {
        this.state.jobText = text || "";
        this.state.jobId = this.resolveIdByLabel(this.jobOptions, text);
        this._saveJob();
        await this._loadRows();
    }

    async onJobSelect(opt) {
        this.state.jobId = opt.id;
        this.state.jobText = opt.label;
        this._saveJob();
        await this._loadRows();
    }

    async _loadRows() {
        this.state.selectedIds = {};
        if (!this.state.jobId) {
            this.state.rows = [];
            return;
        }
        const items = await this.orm.searchRead(
            JOB_EQUIPMENT_ITEM_MODEL, [["job_number", "=", this.state.jobId]],
            ["part_id", "description_en", "description_vn", "used_ports", "open_ports"],
            { order: "sequence, id" }
        );
        this.state.rows = items.map((it) => ({
            id: it.id,
            part_label: it.part_id ? it.part_id[1] : "",
            description_en: it.description_en,
            description_vn: it.description_vn,
            used_ports: it.used_ports,
            open_ports: it.open_ports,
            saving: false,
        }));
    }

    // ---- Column widths - draggable + persisted, same convention as the
    // Create List page (see builder.js's onColumnResizeStart) ----
    _loadColumnWidths() {
        let saved = {};
        try {
            saved = JSON.parse(localStorage.getItem(COLUMN_WIDTHS_STORAGE_KEY) || "{}");
        } catch {
            saved = {};
        }
        return { ...DEFAULT_COLUMN_WIDTHS, ...saved };
    }

    _saveColumnWidths() {
        try {
            localStorage.setItem(COLUMN_WIDTHS_STORAGE_KEY, JSON.stringify(this.state.columnWidths));
        } catch {
            // storage unavailable - widths just won't be remembered next time
        }
    }

    onColumnResizeStart(columnKey, ev) {
        ev.preventDefault();
        const startX = ev.clientX;
        const startWidth = this.state.columnWidths[columnKey];
        const onMouseMove = (moveEv) => {
            this.state.columnWidths[columnKey] = Math.max(60, startWidth + (moveEv.clientX - startX));
        };
        const onMouseUp = () => {
            window.removeEventListener("mousemove", onMouseMove);
            window.removeEventListener("mouseup", onMouseUp);
            this._saveColumnWidths();
        };
        window.addEventListener("mousemove", onMouseMove);
        window.addEventListener("mouseup", onMouseUp);
    }

    // ---- "Add Item" - the Part combobox here doubles as the paste target
    // (see onNewPartPaste) - both stage into pendingRows, nothing is created
    // until Save ----
    _debouncedSearch(key, fn) {
        clearTimeout(this._searchTimers[key]);
        this._searchTimers[key] = setTimeout(fn, SEARCH_DEBOUNCE_MS);
    }

    // 40k+ Part Numbers in this system - never preload them all (see the
    // Excel-paste-by-code path below for why that's fine there but not
    // here). Live server-side search instead, same debounced pattern as
    // part_management_page's own Part/Vendor combobox fields. Carries
    // display_description/_vn straight through, so picking a result can
    // default the Description EN/VN inputs without a second round trip.
    async _searchParts(text) {
        if (!text) {
            this.state.partOptions = [];
            return;
        }
        const parts = await this.orm.searchRead(
            PART_NUMBER_MODEL,
            ["|", ["part_number", "ilike", text], ["display_description", "ilike", text]],
            ["part_number", "display_description", "display_description_vn", "short_description"],
            { limit: SEARCH_LIMIT }
        );
        this.state.partOptions = parts.map((p) => ({
            id: p.id,
            label: `${p.display_description || p.short_description || "(No description)"} (${p.part_number})`,
            description_en: p.display_description || p.part_number,
            description_vn: p.display_description_vn || p.display_description || p.part_number,
        }));
    }

    onNewPartInput(text) {
        this.state.newPartText = text || "";
        this.state.newPartId = false;
        this._debouncedSearch("part", () => this._searchParts(text));
    }

    // Description EN/VN always start from the Part's own Display
    // Description (see _searchParts) - same rule as a pasted row (see
    // JobEquipmentItem._default_descriptions on the Python side). Still
    // editable afterward, both here and once staged in pendingRows.
    onNewPartSelect(opt) {
        this.state.newPartId = opt.id;
        this.state.newPartText = opt.label;
        this.state.newDescriptionEn = opt.description_en;
        this.state.newDescriptionVn = opt.description_vn;
    }

    onAddToPending() {
        if (!this.state.newPartId) {
            this.notification.add("Pick a Part first.", { type: "danger" });
            return;
        }
        this.state.pendingRows.push({
            _localId: Date.now() + Math.random(),
            part_id: this.state.newPartId,
            part_label: this.state.newPartText,
            description_en: this.state.newDescriptionEn || this.state.newPartText,
            description_vn: this.state.newDescriptionVn || this.state.newPartText,
        });
        this.state.newPartId = false;
        this.state.newPartText = "";
        this.state.newDescriptionEn = "";
        this.state.newDescriptionVn = "";
    }

    // A plain single-value paste (e.g. pasting one Part Number into the box
    // to search for it) is left to the combobox's own default text handling.
    // Only a paste that actually looks like an Excel block (tab or multiple
    // lines) is intercepted and staged as pending rows straight away - no
    // separate "click here to paste" zone needed.
    async onNewPartPaste(ev) {
        const text = (ev.clipboardData || window.clipboardData).getData("text");
        if (!text || !(text.includes("\t") || text.includes("\n"))) {
            return;
        }
        ev.preventDefault();
        const result = await this.orm.call(JOB_EQUIPMENT_ITEM_MODEL, "parse_paste", [text]);
        for (const row of result.rows) {
            this.state.pendingRows.push({
                _localId: Date.now() + Math.random(),
                part_id: row.part_id,
                part_label: row.part_label,
                description_en: row.description_en,
                description_vn: row.description_vn,
            });
        }
        if (result.rows.length) {
            this.notification.add(`${result.rows.length} item(s) added to the list below - Save to keep them.`, {
                type: "success",
            });
        }
        if (result.errors.length) {
            this.notification.add(result.errors.join("\n"), {
                type: "warning", sticky: true, title: "Some lines were skipped",
            });
        }
    }

    removePendingRow(localId) {
        this.state.pendingRows = this.state.pendingRows.filter((r) => r._localId !== localId);
    }

    async onSaveClick() {
        if (!this.state.jobId) {
            this.notification.add("Select a Job Number first.", { type: "danger" });
            return;
        }
        if (!this.state.pendingRows.length) {
            this.notification.add("Nothing to save.", { type: "info" });
            return;
        }
        this.state.isSaving = true;
        try {
            await this.orm.create(JOB_EQUIPMENT_ITEM_MODEL, this.state.pendingRows.map((row) => ({
                job_number: this.state.jobId,
                part_id: row.part_id,
                description_en: row.description_en,
                description_vn: row.description_vn,
            })));
            this.notification.add(`${this.state.pendingRows.length} item(s) saved.`, { type: "success" });
            this.state.pendingRows = [];
            await this._loadRows();
            this.props.onRowsChanged?.();
        } finally {
            this.state.isSaving = false;
        }
    }

    // ---- Inline edit / remove on already-saved rows - these are real
    // records already, so edits/removals here take effect immediately,
    // unlike the pending rows above ----
    async onDescriptionBlur(row, field) {
        if (!row[field] || !row[field].trim()) {
            this.notification.add("Description cannot be empty.", { type: "danger" });
            await this._loadRows();
            return;
        }
        row.saving = true;
        try {
            await this.orm.write(JOB_EQUIPMENT_ITEM_MODEL, [row.id], { [field]: row[field] });
        } finally {
            row.saving = false;
        }
    }

    async onRemoveRow(row) {
        await this.orm.unlink(JOB_EQUIPMENT_ITEM_MODEL, [row.id]);
        this.state.rows = this.state.rows.filter((r) => r.id !== row.id);
        delete this.state.selectedIds[row.id];
        this.props.onRowsChanged?.();
    }

    // ---- Multi-select on the already-saved rows table, for bulk delete ----
    get selectedCount() {
        return Object.keys(this.state.selectedIds).length;
    }

    get allRowsSelected() {
        return this.state.rows.length > 0 && this.state.rows.every((r) => this.state.selectedIds[r.id]);
    }

    toggleRowSelected(row) {
        if (this.state.selectedIds[row.id]) {
            delete this.state.selectedIds[row.id];
        } else {
            this.state.selectedIds[row.id] = true;
        }
    }

    toggleSelectAll() {
        if (this.allRowsSelected) {
            this.state.selectedIds = {};
        } else {
            for (const row of this.state.rows) {
                this.state.selectedIds[row.id] = true;
            }
        }
    }

    async onDeleteSelectedClick() {
        const ids = Object.keys(this.state.selectedIds).map(Number);
        if (!ids.length) {
            return;
        }
        if (!window.confirm(`Delete ${ids.length} selected Item(s)? This cannot be undone.`)) {
            return;
        }
        await this.orm.unlink(JOB_EQUIPMENT_ITEM_MODEL, ids);
        this.state.rows = this.state.rows.filter((r) => !ids.includes(r.id));
        this.state.selectedIds = {};
        this.notification.add(`${ids.length} Item(s) deleted.`, { type: "success" });
        this.props.onRowsChanged?.();
    }

    goToBuilder() {
        this.action.doAction("hose_fitting_manager.action_hfm_builder");
    }
}

registry.category("actions").add("hose_fitting_manager.equipment_items", EquipmentItemsPage);
