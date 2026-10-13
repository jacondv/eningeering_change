/** @odoo-module **/

import { Component, onWillStart, useEffect, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { PnmCombobox } from "@part_number_manager/part_management_page/pnm_combobox";
import { EquipmentItemsPage } from "../equipment_items/equipment_items";
import { PortBoard } from "../port_board/port_board";

const PART_NUMBER_MODEL = "part_number_manager.part_number";
const CONFIG_MODEL = "hose_fitting_manager.config";
const CONFIG_OPTION_MODEL = "hose_fitting_manager.config_fitting_option";
const CONFIG_FIRE_WRAP_OPTION_MODEL = "hose_fitting_manager.config_fire_wrap_option";
const CONFIG_HOSE_GUARD_OPTION_MODEL = "hose_fitting_manager.config_hose_guard_option";
const FUNCTION_MODEL = "hose_fitting_manager.function";
const JOB_HOSE_LINE_MODEL = "hose_fitting_manager.job_hose_line";
const DEFAULT_LENGTH_TOLERANCE = 100.0;

const COLUMN_WIDTHS_STORAGE_KEY = "hose_fitting_manager.builder.column_widths";
const DEFAULT_COLUMN_WIDTHS = {
    hose: 160,
    symbol: 130,
    hose_number: 110,
    function: 130,
    wire: 90,
    desc_en: 200,
    desc_vn: 200,
    qty: 70,
    length: 150,
    fitting1: 160,
    ferrule1: 140,
    fitting2: 160,
    ferrule2: 140,
    fire_wrap: 160,
    hose_guard: 160,
    part_number: 130,
};

const COLUMN_VISIBILITY_STORAGE_KEY = "hose_fitting_manager.builder.column_visibility";
// The Job Lines recap table below keeps its own width/visibility choices,
// independent of the Create List table above - same column set and labels,
// but a user may want e.g. Ferrule hidden only on the recap, not while
// actively building.
const JOB_LINES_COLUMN_WIDTHS_STORAGE_KEY = "hose_fitting_manager.builder.job_lines_column_widths";
const JOB_LINES_COLUMN_VISIBILITY_STORAGE_KEY = "hose_fitting_manager.builder.job_lines_column_visibility";
// Column labels double as the toggle list's captions - keep in sync with
// DEFAULT_COLUMN_WIDTHS' keys (Actions is never hideable).
const COLUMN_LABELS = {
    hose: "Hose",
    symbol: "Symbol",
    hose_number: "Hose No",
    function: "Function",
    wire: "Wire",
    desc_en: "Description EN",
    desc_vn: "Description VN",
    qty: "Qty",
    length: "Length (mm)",
    fitting1: "Fitting 1",
    ferrule1: "Ferrule (Fitting 1)",
    fitting2: "Fitting 2",
    ferrule2: "Ferrule (Fitting 2)",
    fire_wrap: "Fire Wrap",
    hose_guard: "Hose Guard",
    part_number: "Part Number",
};
const DEFAULT_COLUMN_VISIBILITY = Object.fromEntries(
    Object.keys(COLUMN_LABELS).map((k) => [k, true])
);

const LAST_JOB_STORAGE_KEY = "hose_fitting_manager.builder.last_job";
// Which page sections are collapsed - {stateKey: bool}, remembered per
// browser like the column widths. Equipment Items starts collapsed (an
// occasional-admin task); the rest start open.
const COLLAPSED_SECTIONS_STORAGE_KEY = "hose_fitting_manager.builder.collapsed_sections";
const DEFAULT_COLLAPSED_SECTIONS = {
    equipmentItemsCollapsed: true,
    portBoardCollapsed: false,
    createListCollapsed: false,
    jobLinesCollapsed: false,
};
const LAST_MATERIAL_GROUP_STORAGE_KEY = "hose_fitting_manager.builder.last_material_group";

const TABLE_HEIGHT_STORAGE_KEY = "hose_fitting_manager.builder.table_height";
const JOB_LINES_HEIGHT_STORAGE_KEY = "hose_fitting_manager.builder.job_lines_height";
const DEFAULT_TABLE_HEIGHT = 500;
const DEFAULT_JOB_LINES_HEIGHT = 320;

export class HoseFittingBuilder extends Component {
    static template = "hose_fitting_manager.Builder";
    static components = { PnmCombobox, EquipmentItemsPage, PortBoard };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.action = useService("action");
        this.dialog = useService("dialog");

        this.state = useState({
            jobText: "",
            jobId: false,
            materialGroupText: "", // only needed for rows that end up generating a new assembly Part
            materialGroupId: false,
            rows: [],
            errors: {},
            isSaving: false,
            jobLines: [], // every Hose and Fitting job_hose_line already saved for state.jobId
            columnWidths: this._loadColumnWidths(COLUMN_WIDTHS_STORAGE_KEY),
            columnVisibility: this._loadColumnVisibility(COLUMN_VISIBILITY_STORAGE_KEY),
            columnMenuOpen: false,
            jobLinesColumnWidths: this._loadColumnWidths(JOB_LINES_COLUMN_WIDTHS_STORAGE_KEY),
            jobLinesColumnVisibility: this._loadColumnVisibility(JOB_LINES_COLUMN_VISIBILITY_STORAGE_KEY),
            jobLinesColumnMenuOpen: false,
            // Equipment Items panel is collapsed by default - it's an
            // occasional-admin task, not the primary flow now that the Port
            // Board is the main way to start a connection. The other
            // sections below default open (the primary flow), but can all
            // be collapsed the same way (see .o_hfm_header_toggle).
            ...this._loadCollapsedSections(),
            // Bumped whenever something may have changed a Port's open/used
            // status (a Wire wizard closed, a batch Save succeeded, an
            // Equipment Item was added/removed) - PortBoard reloads whenever
            // this changes (see its own reloadToken prop/useEffect).
            portBoardReloadToken: 0,
            // Briefly set by onUsedPortClick to flash-highlight the matching
            // recap row instead of navigating anywhere - see builder.xml.
            highlightedJobLineId: false,
            // The saved line currently being edited in place in the Job
            // Lines table - a regular Builder row (see _makeRow) plus its
            // `lineId`, so the same pick/length helpers drive it.
            editingRow: null,
        });

        this.jobOptions = [];
        this.materialGroupOptions = [];
        this.configOptions = []; // [{id, label: symbol}]
        this.configsById = {}; // id -> {id, symbol, hose_id, hose_text,
                                //        fitting_options: [{id, label, ferrule_id, ferrule_label}] (both ends),
                                //        fire_wrap_options: [{id, label}]}
        this.configsByHoseId = {}; // hose Part id -> same config object as above (first match wins)
        this.hoseOptions = []; // [{id, label}] every Hose-type Part - the primary pick now
        this.functionOptions = []; // [{id, label}] every Function - shared list, not tied to Symbol/Config
        this.columnLabels = COLUMN_LABELS;
        this.columnKeys = Object.keys(COLUMN_LABELS);
        // "Wire" is an action column (a button, not real data) - always
        // shown, so left out of the show/hide toggle menu.
        this.toggleableColumnKeys = this.columnKeys.filter((k) => k !== "wire");
        // Wire only applies to rows still being built (top table) - once a
        // line is saved and shows up here, it's wired via the row it came
        // from, not from this read-only recap.
        this.recapColumnKeys = this.columnKeys.filter((k) => k !== "wire");
        // The row helpers the Port Board's inline lines share with the
        // Manual Lines table - one implementation of Hose/Fitting/Length
        // picking, not a copy per table.
        this.rowApi = {
            makeRow: () => this._makeRow(),
            pickHose: (row, opt) => this._pickHose(row, opt),
            setHoseText: (row, text) => this._setHoseText(row, text),
            pickFitting: (row, slot, opt) => this._pickFittingOption(row, slot, opt),
            setFittingText: (row, slot, text) => this._setFittingText(row, slot, text),
            pickFireWrap: (row, opt) => this._pickFireWrap(row, opt),
            setFireWrapText: (row, text) => this._setFireWrapText(row, text),
            pickHoseGuard: (row, opt) => this._pickHoseGuard(row, opt),
            setHoseGuardText: (row, text) => this._setHoseGuardText(row, text),
            pickFunction: (row, opt) => this._pickFunction(row, opt),
            setFunctionText: (row, text) => this._setFunctionText(row, text),
            setLengthText: (row, text) => this._setLengthText(row, text),
            selectLengthMatch: (row, opt) => this._selectLengthMatch(row, opt),
            lengthBlur: (row) => this.onLengthBlur(row),
        };

        this.tableWrapperRef = useRef("tableWrapper");
        this.jobLinesWrapperRef = useRef("jobLinesWrapper");

        // Re-attaches whenever the Create List section is collapsed/expanded
        // too, not just on mount - its ResizeObserver target element gets
        // torn down and recreated each time state.createListCollapsed
        // toggles (see builder.xml's t-if), same reasoning as the Job Lines
        // table's own effect right below.
        useEffect(
            () => {
                if (!this.state.createListCollapsed) {
                    return this._setupResizePersistence(
                        this.tableWrapperRef, TABLE_HEIGHT_STORAGE_KEY, DEFAULT_TABLE_HEIGHT
                    );
                }
            },
            () => [this.state.createListCollapsed]
        );
        // The Job Lines table only exists in the DOM once state.jobLines is
        // non-empty and the section isn't collapsed (see builder.xml's
        // t-if) - (re)attach whenever either changes, since its
        // ResizeObserver target element gets recreated each time the table
        // toggles off and back on.
        useEffect(
            () => {
                if (this.state.jobLines.length && !this.state.jobLinesCollapsed) {
                    return this._setupResizePersistence(
                        this.jobLinesWrapperRef, JOB_LINES_HEIGHT_STORAGE_KEY, DEFAULT_JOB_LINES_HEIGHT
                    );
                }
            },
            () => [this.state.jobLines.length > 0, this.state.jobLinesCollapsed]
        );

        onWillStart(async () => {
            await Promise.all([
                this._loadJobs(), this._loadMaterialGroups(), this._loadConfigs(), this._loadFunctions(),
            ]);
            this._restoreLastJob();
            this._restoreLastMaterialGroup();
            this.addRow();
            this._loadJobLines();
        });
    }

    // Every Hose and Fitting line already saved for the currently selected
    // Job Number - not just what's been added this session (state.recentLines
    // only covers that) - shown read-only below the Save button, refreshed
    // whenever the Job changes or a new batch is saved. Same column set and
    // order as the Create List table above, but its own independent
    // show/hide and width choices (state.jobLinesColumnWidths/Visibility) -
    // only Display Names are shown for Hose/Fitting/Ferrule/Fire Wrap, never
    // the raw Part Number code.
    async _loadJobLines() {
        if (!this.state.jobId) {
            this.state.jobLines = [];
            return;
        }
        const lines = await this.orm.searchRead(
            JOB_HOSE_LINE_MODEL, [["job_number", "=", this.state.jobId]],
            ["config_id", "hose_id", "hose_number", "function_id", "description_en", "description_vn",
             "quantity", "length",
             "fitting1_id", "ferrule1_id", "fitting2_id", "ferrule2_id", "fire_wrap_id", "hose_guard_id", "part_id"]
        );

        const partIds = new Set();
        for (const l of lines) {
            for (const key of ["hose_id", "fitting1_id", "ferrule1_id", "fitting2_id", "ferrule2_id", "fire_wrap_id", "hose_guard_id"]) {
                if (l[key]) partIds.add(l[key][0]);
            }
        }
        const parts = partIds.size
            ? await this.orm.read(
                  PART_NUMBER_MODEL, [...partIds], ["display_description", "short_description", "part_number"]
              )
            : [];
        const labelById = {};
        for (const p of parts) {
            labelById[p.id] =
                p.display_description || p.short_description || `(No description) ${p.part_number}`;
        }
        const label = (field) => (field ? labelById[field[0]] || "" : "");

        this.state.jobLines = lines.map((l) => ({
            id: l.id,
            raw: l, // the record as read - startEditJobLine builds its edit row from these ids
            part_id: l.part_id ? l.part_id[0] : false,
            hose: label(l.hose_id),
            symbol: l.config_id ? l.config_id[1] : "",
            hose_number: l.hose_number,
            function: l.function_id ? l.function_id[1] : "",
            desc_en: l.description_en,
            desc_vn: l.description_vn,
            qty: l.quantity,
            length: l.length,
            fitting1: label(l.fitting1_id),
            ferrule1: label(l.ferrule1_id),
            fitting2: label(l.fitting2_id),
            ferrule2: label(l.ferrule2_id),
            fire_wrap: label(l.fire_wrap_id),
            hose_guard: label(l.hose_guard_id),
            part_number: l.part_id ? l.part_id[1] : "",
        }));
    }

    // Job Number and Material Group are re-picked on every list a user
    // builds - remembering the last one used saves re-typing it every time,
    // same idea as column widths. Only restored if it still resolves to a
    // real option (deleted/renamed Job or Group just leaves the field blank).
    _restoreLastJob() {
        let saved = null;
        try {
            saved = JSON.parse(localStorage.getItem(LAST_JOB_STORAGE_KEY) || "null");
        } catch {
            saved = null;
        }
        if (saved && this.jobOptions.some((o) => o.id === saved.id)) {
            this.state.jobText = saved.label;
            this.state.jobId = saved.id;
        }
    }

    _restoreLastMaterialGroup() {
        let saved = null;
        try {
            saved = JSON.parse(localStorage.getItem(LAST_MATERIAL_GROUP_STORAGE_KEY) || "null");
        } catch {
            saved = null;
        }
        if (saved && this.materialGroupOptions.some((o) => o.id === saved.id)) {
            this.state.materialGroupText = saved.label;
            this.state.materialGroupId = saved.id;
        }
    }

    _saveLastJob() {
        try {
            if (this.state.jobId) {
                localStorage.setItem(
                    LAST_JOB_STORAGE_KEY,
                    JSON.stringify({ id: this.state.jobId, label: this.state.jobText })
                );
            } else {
                localStorage.removeItem(LAST_JOB_STORAGE_KEY);
            }
        } catch {
            // storage unavailable - nothing else depends on it
        }
    }

    _saveLastMaterialGroup() {
        try {
            if (this.state.materialGroupId) {
                localStorage.setItem(
                    LAST_MATERIAL_GROUP_STORAGE_KEY,
                    JSON.stringify({ id: this.state.materialGroupId, label: this.state.materialGroupText })
                );
            } else {
                localStorage.removeItem(LAST_MATERIAL_GROUP_STORAGE_KEY);
            }
        } catch {
            // storage unavailable - nothing else depends on it
        }
    }

    async _loadJobs() {
        const jobs = await this.orm.searchRead("project.project", [], ["name"]);
        this.jobOptions = jobs.filter((j) => j.name).map((j) => ({ id: j.id, label: j.name }));
    }

    // A flat, shared list of Functions (Configuration > Functions) - never
    // filtered by Symbol/Config, unlike Fitting/Fire Wrap/Hose Guard options.
    async _loadFunctions() {
        const functions = await this.orm.searchRead(FUNCTION_MODEL, [], ["name"]);
        this.functionOptions = functions.map((f) => ({ id: f.id, label: f.name }));
    }

    async _loadMaterialGroups() {
        const groups = await this.orm.searchRead(
            "part_number_manager.material_group", [], ["code", "description"]
        );
        this.materialGroupOptions = groups.map((g) => ({ id: g.id, label: `${g.code} - ${g.description}` }));
    }

    // Loads every Hose And Fitting Config + its Fitting/Fire Wrap options in
    // one shot, then resolves every referenced Part's display label in a
    // single batch read - avoids a round trip per row later on when a
    // Symbol is picked.
    async _loadConfigs() {
        const configs = await this.orm.searchRead(CONFIG_MODEL, [], ["symbol", "hose_id"]);
        const options = await this.orm.searchRead(
            CONFIG_OPTION_MODEL, [], ["config_id", "fitting_id", "ferrule_id"]
        );
        const fireWrapOptions = await this.orm.searchRead(
            CONFIG_FIRE_WRAP_OPTION_MODEL, [], ["config_id", "fire_wrap_id"]
        );
        const hoseGuardOptions = await this.orm.searchRead(
            CONFIG_HOSE_GUARD_OPTION_MODEL, [], ["config_id", "hose_guard_id"]
        );

        const partIds = new Set();
        for (const c of configs) {
            if (c.hose_id) partIds.add(c.hose_id[0]);
        }
        for (const o of options) {
            if (o.fitting_id) partIds.add(o.fitting_id[0]);
            if (o.ferrule_id) partIds.add(o.ferrule_id[0]);
        }
        for (const f of fireWrapOptions) {
            if (f.fire_wrap_id) partIds.add(f.fire_wrap_id[0]);
        }
        for (const g of hoseGuardOptions) {
            if (g.hose_guard_id) partIds.add(g.hose_guard_id[0]);
        }
        const parts = partIds.size
            ? await this.orm.read(
                  PART_NUMBER_MODEL, [...partIds], ["display_description", "short_description", "part_number"]
              )
            : [];
        // Never leads with the raw Part Number code - only shown as a
        // clearly-marked fallback when a Part has no description at all, so
        // it never ends up as a blank, invisible/unclickable dropdown row.
        const labelById = {};
        for (const p of parts) {
            labelById[p.id] =
                p.display_description || p.short_description || `(No description) ${p.part_number}`;
        }

        this.configOptions = configs.map((c) => ({ id: c.id, label: c.symbol }));
        this.configsById = {};
        for (const c of configs) {
            this.configsById[c.id] = {
                id: c.id,
                symbol: c.symbol,
                hose_id: c.hose_id ? c.hose_id[0] : false,
                hose_text: c.hose_id ? labelById[c.hose_id[0]] : "",
                fitting_options: [],
                fire_wrap_options: [],
                hose_guard_options: [],
            };
        }
        for (const o of options) {
            const cfg = this.configsById[o.config_id[0]];
            if (!cfg) continue;
            const entry = {
                id: o.fitting_id[0],
                label: labelById[o.fitting_id[0]],
                ferrule_id: o.ferrule_id ? o.ferrule_id[0] : false,
                ferrule_label: o.ferrule_id ? labelById[o.ferrule_id[0]] : "",
            };
            cfg.fitting_options.push(entry);
        }
        for (const f of fireWrapOptions) {
            const cfg = this.configsById[f.config_id[0]];
            if (!cfg) continue;
            cfg.fire_wrap_options.push({ id: f.fire_wrap_id[0], label: labelById[f.fire_wrap_id[0]] });
        }
        for (const g of hoseGuardOptions) {
            const cfg = this.configsById[g.config_id[0]];
            if (!cfg) continue;
            cfg.hose_guard_options.push({ id: g.hose_guard_id[0], label: labelById[g.hose_guard_id[0]] });
        }

        // A Hose can now be picked directly (see _pickHose) instead of only
        // via its Symbol - the Symbol becomes a derived, read-only display
        // once a Hose is picked (looked up by matching Config.hose_id).
        // Loaded separately from configs/options above since a Hose Part
        // may exist without any Config referencing it yet.
        this.configsByHoseId = {};
        for (const cfg of Object.values(this.configsById)) {
            if (cfg.hose_id && !(cfg.hose_id in this.configsByHoseId)) {
                this.configsByHoseId[cfg.hose_id] = cfg;
            }
        }
        // Only Hoses actually referenced by a Hose And Fitting Config -
        // never every Hose-type Part Number in the system - so the Port
        // Board/Create List's Hose picker only ever offers Hoses someone
        // has deliberately set up a Config for (with its own Fitting/
        // Ferrule/Fire Wrap/Hose Guard options), same source `configs`
        // above already loaded, not a separate broader query.
        // Labelled "[Symbol] Description" (e.g. [A] 1/4" x 1SN) - the
        // Symbol is what people know a Hose by on the drawings.
        const hoseIds = [...new Set(configs.filter((c) => c.hose_id).map((c) => c.hose_id[0]))];
        this.hoseOptions = hoseIds.map((id) => ({
            id,
            label: `[${this.configsByHoseId[id].symbol}] ${labelById[id] || "(No description)"}`,
        }));
    }

    resolveIdByLabel(options, text) {
        const norm = (text || "").trim().toLowerCase();
        if (!norm) {
            return false;
        }
        const match = options.find((o) => String(o.label || "").toLowerCase() === norm);
        return match ? match.id : false;
    }

    // Applies the last saved height (native CSS `resize: vertical` on the
    // element - see builder.scss) and persists whatever height the user
    // drags it to next, via ResizeObserver (there's no native "resize"
    // event for CSS resize handles). Returns a cleanup function that
    // disconnects the observer, for useEffect/onMounted to call it.
    _setupResizePersistence(ref, storageKey, defaultHeight) {
        if (!ref.el) {
            return;
        }
        let saved = defaultHeight;
        try {
            const stored = localStorage.getItem(storageKey);
            if (stored) {
                saved = parseInt(stored, 10) || defaultHeight;
            }
        } catch {
            saved = defaultHeight;
        }
        ref.el.style.height = `${saved}px`;

        const observer = new ResizeObserver((entries) => {
            for (const entry of entries) {
                const height = Math.round(entry.contentRect.height);
                try {
                    localStorage.setItem(storageKey, String(height));
                } catch {
                    // storage unavailable - height just won't be remembered
                }
            }
        });
        observer.observe(ref.el);
        return () => observer.disconnect();
    }

    _loadColumnWidths(storageKey) {
        let saved = {};
        try {
            saved = JSON.parse(localStorage.getItem(storageKey) || "{}");
        } catch {
            saved = {};
        }
        return { ...DEFAULT_COLUMN_WIDTHS, ...saved };
    }

    _saveColumnWidths(storageKey, widths) {
        try {
            localStorage.setItem(storageKey, JSON.stringify(widths));
        } catch {
            // Private browsing / storage disabled / quota - column widths
            // just won't be remembered next time, nothing else depends on it.
        }
    }

    _loadCollapsedSections() {
        let saved = {};
        try {
            saved = JSON.parse(localStorage.getItem(COLLAPSED_SECTIONS_STORAGE_KEY) || "{}");
        } catch {
            saved = {};
        }
        const sections = { ...DEFAULT_COLLAPSED_SECTIONS };
        for (const key of Object.keys(sections)) {
            if (typeof saved[key] === "boolean") {
                sections[key] = saved[key];
            }
        }
        return sections;
    }

    toggleSection(stateKey) {
        this.state[stateKey] = !this.state[stateKey];
        const sections = Object.fromEntries(
            Object.keys(DEFAULT_COLLAPSED_SECTIONS).map((key) => [key, this.state[key]])
        );
        try {
            localStorage.setItem(COLLAPSED_SECTIONS_STORAGE_KEY, JSON.stringify(sections));
        } catch {
            // storage unavailable - just won't be remembered next time
        }
    }

    _loadColumnVisibility(storageKey) {
        let saved = {};
        try {
            saved = JSON.parse(localStorage.getItem(storageKey) || "{}");
        } catch {
            saved = {};
        }
        return { ...DEFAULT_COLUMN_VISIBILITY, ...saved };
    }

    _saveColumnVisibility(storageKey, visibility) {
        try {
            localStorage.setItem(storageKey, JSON.stringify(visibility));
        } catch {
            // storage unavailable - column choices just won't be remembered
        }
    }

    toggleColumnMenu() {
        this.state.columnMenuOpen = !this.state.columnMenuOpen;
    }

    toggleColumnVisibility(columnKey) {
        this.state.columnVisibility[columnKey] = !this.state.columnVisibility[columnKey];
        this._saveColumnVisibility(COLUMN_VISIBILITY_STORAGE_KEY, this.state.columnVisibility);
    }

    onColumnResizeStart(columnKey, ev) {
        this._startColumnResize(this.state.columnWidths, COLUMN_WIDTHS_STORAGE_KEY, columnKey, ev);
    }

    // ---- Job Lines recap table - same mechanics as above, own state/keys ----
    toggleJobLinesColumnMenu() {
        this.state.jobLinesColumnMenuOpen = !this.state.jobLinesColumnMenuOpen;
    }

    toggleJobLinesColumnVisibility(columnKey) {
        this.state.jobLinesColumnVisibility[columnKey] = !this.state.jobLinesColumnVisibility[columnKey];
        this._saveColumnVisibility(JOB_LINES_COLUMN_VISIBILITY_STORAGE_KEY, this.state.jobLinesColumnVisibility);
    }

    onJobLinesColumnResizeStart(columnKey, ev) {
        this._startColumnResize(
            this.state.jobLinesColumnWidths, JOB_LINES_COLUMN_WIDTHS_STORAGE_KEY, columnKey, ev);
    }

    _startColumnResize(widths, storageKey, columnKey, ev) {
        ev.preventDefault();
        const startX = ev.clientX;
        const startWidth = widths[columnKey];
        const onMouseMove = (moveEv) => {
            widths[columnKey] = Math.max(60, startWidth + (moveEv.clientX - startX));
        };
        const onMouseUp = () => {
            window.removeEventListener("mousemove", onMouseMove);
            window.removeEventListener("mouseup", onMouseUp);
            this._saveColumnWidths(storageKey, widths);
        };
        window.addEventListener("mousemove", onMouseMove);
        window.addEventListener("mouseup", onMouseUp);
    }

    _setJobText(text) {
        this.state.jobText = text || "";
        this.state.jobId = this.resolveIdByLabel(this.jobOptions, text);
        this._saveLastJob();
        this._loadJobLines();
    }

    _setMaterialGroupText(text) {
        this.state.materialGroupText = text || "";
        this.state.materialGroupId = this.resolveIdByLabel(this.materialGroupOptions, text);
        this._saveLastMaterialGroup();
    }

    async openJobLine(id) {
        await this.action.doAction({
            type: "ir.actions.act_window",
            res_model: JOB_HOSE_LINE_MODEL,
            res_id: id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    // Deletes an already-saved Hose And Fitting line straight from the
    // recap table - stops the row's own click (which would otherwise also
    // open the line's form) and confirms first since this can't be undone.
    // Reloads the recap list and bumps the Port Board's reload token so any
    // Port this line had wired goes back to Open immediately.
    async onDeleteJobLine(ev, lineId) {
        ev.stopPropagation();
        if (!window.confirm("Delete this Hose And Fitting line? This cannot be undone.")) {
            return;
        }
        await this.orm.unlink(JOB_HOSE_LINE_MODEL, [lineId]);
        await this._loadJobLines();
        this.state.portBoardReloadToken++;
    }

    // Ports already picked on a *pending* (unsaved) row anywhere in
    // state.rows - the Port Board shows these as "Reserved" (distinct from
    // the server's own Open/Used) so two rows in the same session can't
    // both claim the same port before either is saved. A row already
    // status==='success' is real DB state by now, already reflected as
    // "used" by the Board's own next reload - excluded here so it isn't
    // double-counted as merely "reserved".
    get reservedPortIds() {
        const ids = new Set();
        for (const row of this.state.rows) {
            if (row.status === "success") continue;
            if (row.from_port_id) ids.add(row.from_port_id);
            if (row.to_port_id) ids.add(row.to_port_id);
        }
        return ids;
    }

    // From/To Description for a wired line - computed by silently
    // creating+reading+discarding a wire_wizard record (same formula its
    // own preview uses - see wire_wizard.py - never duplicated here).
    async _previewWireDescription(fromItem, fromPort, toItem, toPort) {
        const [wizardId] = await this.orm.create("hose_fitting_manager.wire_wizard", [{
            job_number: this.state.jobId,
            from_item_id: fromItem.id,
            from_port_id: fromPort.id,
            to_item_id: toItem.id,
            to_port_id: toPort.id,
        }]);
        const [wiz] = await this.orm.read(
            "hose_fitting_manager.wire_wizard", [wizardId],
            ["description_preview_en", "description_preview_vn"]
        );
        await this.orm.unlink("hose_fitting_manager.wire_wizard", [wizardId]);
        return { en: wiz.description_preview_en, vn: wiz.description_preview_vn };
    }

    // Port Board's inline check button - everything is already picked on
    // the Port row itself, so the line is created right away (no Manual
    // Lines detour, no separate Save). Returns {success, error} for the
    // Board to show on that line; on success the new line shows up
    // highlighted in the Job Lines table and the Port turns Used.
    async createFromPortBoard(fromItem, fromPort, toItem, toPort, draft) {
        const description = await this._previewWireDescription(fromItem, fromPort, toItem, toPort);
        const row = {
            ...draft,
            hose_number: this._nextHoseNumber(draft.config_text, null),
            from_item_id: fromItem.id,
            from_port_id: fromPort.id,
            to_item_id: toItem.id,
            to_port_id: toPort.id,
            description_en: description.en,
            description_vn: description.vn,
        };
        const [result] = await this.orm.call(JOB_HOSE_LINE_MODEL, "create_batch", [[this._rowPayload(row)]]);
        if (!result.success) {
            return { success: false, error: result.error };
        }
        this.notification.add(`Created ${row.hose_number || "line"} → ${result.part_number}`, { type: "success" });
        await this._loadJobLines();
        this.state.portBoardReloadToken++;
        // The new row only exists in the DOM after the next render.
        requestAnimationFrame(() => this.onUsedPortClick(result.id));
        return { success: true };
    }

    // Port Board's click on a Used port - never navigates away, just
    // scrolls to and briefly highlights that line's row in the read-only
    // recap table below, which already lists every saved line for this Job.
    onUsedPortClick(jobHoseLineId) {
        const el = this.jobLinesWrapperRef.el?.querySelector(
            `[data-job-line-id="${jobHoseLineId}"]`
        );
        if (!el) {
            return;
        }
        el.scrollIntoView({ behavior: "smooth", block: "center" });
        this.state.highlightedJobLineId = jobHoseLineId;
        setTimeout(() => {
            if (this.state.highlightedJobLineId === jobHoseLineId) {
                this.state.highlightedJobLineId = false;
            }
        }, 1500);
    }

    // Wire, called from a still-unsaved Create List row - there's no
    // job_hose_line to hang the wizard off of yet, so a wire_wizard record
    // is created directly (job_number from this page, not from a line),
    // opened, and its result read back into the row's own state once
    // closed. Nothing is written to job_hose_line here - the picks just
    // ride along in the row and get sent as part of the row's own payload
    // on Save (see onSaveClick).
    async openRowWireWizard(row) {
        if (!this.state.jobId) {
            this.notification.add("Select a Job Number first.", { type: "danger" });
            return;
        }
        // Ports already picked on *other* pending rows in this same batch -
        // not yet reflected in the database, so the wizard wouldn't
        // otherwise know to treat them as taken.
        const excludePortIds = [];
        for (const other of this.state.rows) {
            if (other === row) continue;
            if (other.from_port_id) excludePortIds.push(other.from_port_id);
            if (other.to_port_id) excludePortIds.push(other.to_port_id);
        }

        const [wizardId] = await this.orm.create("hose_fitting_manager.wire_wizard", [{
            job_number: this.state.jobId,
            from_item_id: row.from_item_id || false,
            from_port_id: row.from_port_id || false,
            to_item_id: row.to_item_id || false,
            to_port_id: row.to_port_id || false,
            exclude_port_ids: [[6, 0, excludePortIds]],
        }]);
        // unlink must happen *inside* onClose, not after doAction resolves -
        // for a target:"new" dialog, doAction's own promise resolves once
        // the dialog is opened, not once it's closed, so unlinking straight
        // after it would delete the record while the user is still picking.
        await this.action.doAction(
            {
                type: "ir.actions.act_window",
                res_model: "hose_fitting_manager.wire_wizard",
                res_id: wizardId,
                views: [[false, "form"]],
                target: "new",
            },
            {
                onClose: async () => {
                    const [wiz] = await this.orm.read(
                        "hose_fitting_manager.wire_wizard", [wizardId],
                        ["from_item_id", "from_port_id", "to_item_id", "to_port_id",
                         "description_preview_en", "description_preview_vn"]
                    );
                    if (wiz.from_item_id && wiz.from_port_id && wiz.to_item_id && wiz.to_port_id) {
                        row.from_item_id = wiz.from_item_id[0];
                        row.from_port_id = wiz.from_port_id[0];
                        row.to_item_id = wiz.to_item_id[0];
                        row.to_port_id = wiz.to_port_id[0];
                        row.description_en = wiz.description_preview_en;
                        row.description_vn = wiz.description_preview_vn;
                    }
                    await this.orm.unlink("hose_fitting_manager.wire_wizard", [wizardId]);
                    this.state.portBoardReloadToken++;
                },
            }
        );
    }

    _escapeRegExp(text) {
        return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    }

    // "<Symbol><Number>" (A0, A1, A2... B0, B1...) - the next free number for
    // this Symbol, continuing from every Hose Number already used for it in
    // this Job: both already-saved lines (state.jobLines) and other rows
    // still being edited in this same batch (so two new rows for the same
    // Symbol in one session don't collide before either is saved).
    _nextHoseNumber(symbol, currentRow) {
        if (!symbol) {
            return "";
        }
        const re = new RegExp(`^${this._escapeRegExp(symbol)}(\\d+)$`);
        let max = -1;
        for (const l of this.state.jobLines) {
            if (l.symbol === symbol) {
                const m = re.exec(l.hose_number || "");
                if (m) max = Math.max(max, parseInt(m[1], 10));
            }
        }
        for (const row of this.state.rows) {
            if (row === currentRow) continue;
            if (row.config_text === symbol) {
                const m = re.exec(row.hose_number || "");
                if (m) max = Math.max(max, parseInt(m[1], 10));
            }
        }
        return `${symbol}${max + 1}`;
    }

    _makeRow() {
        return {
            _localId: Date.now() + Math.random(),
            config_id: false,
            config_text: "",
            hose_id: false,
            hose_text: "",
            length: false,
            length_text: "",
            length_tolerance: DEFAULT_LENGTH_TOLERANCE,
            all_length_options: [], // every Part matching the row's BOM (Hose/Fitting1/Fitting2/Ferrules), any Length
            length_options: [], // all_length_options narrowed to the currently typed Length +/- tolerance
                                 // (or a plain copy of all_length_options while Length is blank)
            fitting_options: [], // the Config's Fitting list - offered for both Fitting 1 and Fitting 2
            fitting1_id: false,
            fitting1_text: "",
            ferrule1_id: false,
            ferrule1_text: "",
            fitting2_id: false,
            fitting2_text: "",
            ferrule2_id: false,
            ferrule2_text: "",
            fire_wrap_options: [],
            fire_wrap_id: false,
            fire_wrap_text: "",
            hose_guard_options: [],
            hose_guard_id: false,
            hose_guard_text: "",
            hose_number: "",
            function_id: false,
            function_text: "",
            // Set only via openRowWireWizard - carried into the create_batch
            // payload as-is on Save, so a line can be born already Wired
            // instead of needing a second Wire pass after saving.
            from_item_id: false,
            from_port_id: false,
            to_item_id: false,
            to_port_id: false,
            description_en: "",
            description_vn: "",
            quantity: 1,
            part_id: false, // set only via an explicit pick from length_options - see _selectLengthMatch
            resolved_part_number: "",
            status: "pending", // pending | success | error
            errorMessage: null,
        };
    }

    addRow() {
        this.state.rows.push(this._makeRow());
    }

    // True for a row nothing has been filled in on yet (the always-present
    // trailing blank row from onWillStart/addRow, before the user has typed
    // or picked anything into it) - skipped by Save and its validation, so
    // a blank trailing row is never reported as an error.
    _isRowEmpty(row) {
        return (
            row.status === "pending" &&
            !row.config_id && !row.hose_id && !row.fitting1_id && !row.fitting2_id &&
            !row.ferrule1_id && !row.ferrule2_id && !row.fire_wrap_id && !row.hose_guard_id &&
            !row.hose_number && !row.function_id &&
            !row.from_item_id && !row.to_item_id &&
            row.length === false
        );
    }

    removeRow(localId) {
        this.state.rows = this.state.rows.filter((r) => r._localId !== localId);
    }

    // Picking a Hose directly is now the primary action on a row (it's a
    // real dropdown of every Hose Part, by Display Name) - Hose Symbol
    // keeps its original meaning (the Config's symbol) but is now derived:
    // looked up by matching the picked Hose against Config.hose_id, and
    // shown read-only. When a match is found it pre-fills the first Fitting
    // option for each position - still editable per row - same as Symbol
    // selection used to; when there's no Config for this Hose yet, Symbol
    // just shows blank and Fitting 1/2 have nothing to offer until one is
    // configured (see Hose And Fitting Config).
    _setHoseText(row, text) {
        row.hose_text = text || "";
        const id = this.resolveIdByLabel(this.hoseOptions, text);
        this._pickHose(row, id ? { id, label: row.hose_text } : null);
    }

    _pickHose(row, opt) {
        row.hose_id = opt ? opt.id : false;
        row.hose_text = opt ? opt.label : row.hose_text;

        const cfg = row.hose_id ? this.configsByHoseId[row.hose_id] : null;
        if (cfg) {
            row.config_id = cfg.id;
            row.config_text = cfg.symbol;
            row.fitting_options = cfg.fitting_options;
            row.fire_wrap_options = cfg.fire_wrap_options;
            row.hose_guard_options = cfg.hose_guard_options;
            this._pickFittingOption(row, 1, cfg.fitting_options[0] || null);
            this._pickFittingOption(row, 2, cfg.fitting_options[0] || null);
            // Fire Wrap/Hose Guard are never pre-selected, even if the
            // Symbol has option(s) configured - always an explicit pick by
            // the user.
            this._pickFireWrap(row, null);
            this._pickHoseGuard(row, null);
            // Hose Number defaults to "<Symbol><next free number>" the
            // moment a Hose is picked - only when still blank, so it never
            // clobbers a value the user already typed by hand.
            if (!row.hose_number) {
                row.hose_number = this._nextHoseNumber(cfg.symbol, row);
            }
        } else {
            row.config_id = false;
            row.config_text = "";
            row.fitting_options = [];
            row.fire_wrap_options = [];
            row.hose_guard_options = [];
            this._pickFittingOption(row, 1, null);
            this._pickFittingOption(row, 2, null);
            this._pickFireWrap(row, null);
            this._pickHoseGuard(row, null);
        }
        this._refreshAllLengthOptions(row);
    }

    _pickFittingOption(row, slot, opt) {
        const idKey = slot === 1 ? "fitting1_id" : "fitting2_id";
        const textKey = slot === 1 ? "fitting1_text" : "fitting2_text";
        const ferruleIdKey = slot === 1 ? "ferrule1_id" : "ferrule2_id";
        const ferruleTextKey = slot === 1 ? "ferrule1_text" : "ferrule2_text";
        row[idKey] = opt ? opt.id : false;
        row[textKey] = opt ? opt.label : "";
        row[ferruleIdKey] = opt ? opt.ferrule_id : false;
        row[ferruleTextKey] = opt ? opt.ferrule_label : "";
        this._refreshAllLengthOptions(row);
    }

    _setFittingText(row, slot, text) {
        const opt = row.fitting_options.find((o) => o.label.toLowerCase() === (text || "").trim().toLowerCase());
        this._pickFittingOption(row, slot, opt || null);
        if (!opt) {
            const idKey = slot === 1 ? "fitting1_text" : "fitting2_text";
            row[idKey] = text || "";
        }
    }

    // Fire Wrap works exactly like the Fitting 1/2 dropdowns - a list of
    // allowed options for the current Symbol, none pre-selected. Picking
    // one adds it to the assembly; leaving it blank means no Fire Wrap.
    // Deliberately never affects Length matching (see
    // _refreshAllLengthOptions), so no re-query is needed here.
    _pickFireWrap(row, opt) {
        row.fire_wrap_id = opt ? opt.id : false;
        row.fire_wrap_text = opt ? opt.label : "";
    }

    _setFireWrapText(row, text) {
        const opt = row.fire_wrap_options.find(
            (o) => o.label.toLowerCase() === (text || "").trim().toLowerCase()
        );
        this._pickFireWrap(row, opt || null);
        if (!opt) {
            row.fire_wrap_text = text || "";
        }
    }

    // Hose Guard works exactly like Fire Wrap - a list of allowed options
    // for the current Symbol, none pre-selected, never affects Length
    // matching.
    _pickHoseGuard(row, opt) {
        row.hose_guard_id = opt ? opt.id : false;
        row.hose_guard_text = opt ? opt.label : "";
    }

    _setHoseGuardText(row, text) {
        const opt = row.hose_guard_options.find(
            (o) => o.label.toLowerCase() === (text || "").trim().toLowerCase()
        );
        this._pickHoseGuard(row, opt || null);
        if (!opt) {
            row.hose_guard_text = text || "";
        }
    }

    // Function is a flat, shared pick-list (this.functionOptions) - not
    // filtered by Symbol/Config, never affects Length matching or BOM.
    _pickFunction(row, opt) {
        row.function_id = opt ? opt.id : false;
        row.function_text = opt ? opt.label : "";
    }

    _setFunctionText(row, text) {
        const opt = this.functionOptions.find(
            (o) => o.label.toLowerCase() === (text || "").trim().toLowerCase()
        );
        this._pickFunction(row, opt || null);
        if (!opt) {
            row.function_text = text || "";
        }
    }

    // Typing a Length is never itself a pick - it only narrows down
    // `all_length_options` (already loaded - see _refreshAllLengthOptions)
    // to whatever's within tolerance, entirely client-side (no round trip
    // per keystroke). Only an explicit choice from the dropdown
    // (_selectLengthMatch) counts as reusing an existing Part; otherwise
    // the typed number is what gets used to generate a new one on Save.
    _setLengthText(row, text) {
        row.length_text = text || "";
        const parsed = parseFloat(text);
        row.length = Number.isFinite(parsed) ? parsed : false;
        row.part_id = false;
        row.resolved_part_number = "";
        this._recomputeLengthOptions(row);
    }

    _selectLengthMatch(row, opt) {
        row.length = opt.length;
        row.length_text = String(opt.length);
        row.part_id = opt.id;
        row.resolved_part_number = opt.part_number;
    }

    // Rounds a freshly-typed Length to the *nearest* standard increment -
    // 50mm steps under 1000mm, 100mm steps from 1000mm up (e.g. 654 -> 650,
    // not 700) - so slightly different typed lengths converge on the same
    // value instead of each spawning its own Part.
    _roundLengthNearest(value) {
        const step = value < 1000 ? 50 : 100;
        return Math.round(value / step) * step;
    }

    // Only runs once typing is done (on blur) and only when nothing was
    // explicitly picked from the dropdown - an explicit pick (_selectLengthMatch)
    // is trusted as-is, no rounding or re-checking. Otherwise: round the
    // typed value to the nearest standard increment, then check whether a
    // Part at exactly that rounded Length already exists for this row's BOM
    // (regardless of Tolerance - this is an exact-length check, not a
    // tolerance match) - if so, silently reuse it; if not, the rounded
    // value is what gets used to generate a new Part on Save.
    onLengthBlur(row) {
        if (row.part_id || row.length === false) {
            return;
        }
        const rounded = this._roundLengthNearest(row.length);
        row.length = rounded;
        row.length_text = String(rounded);
        this._recomputeLengthOptions(row);

        const exact = (row.all_length_options || []).find((o) => o.length === rounded);
        if (exact) {
            row.part_id = exact.id;
            row.resolved_part_number = exact.part_number;
        }
    }

    // Empty Length (nothing typed yet, e.g. right after focusing the
    // field) shows every loaded option - typing a number narrows it down
    // to whatever's within the row's current tolerance of that number.
    _recomputeLengthOptions(row) {
        const source = row.all_length_options || [];
        if (row.length === false) {
            row.length_options = source;
            return;
        }
        const tolerance = row.length_tolerance || DEFAULT_LENGTH_TOLERANCE;
        row.length_options = source.filter((o) => Math.abs(o.length - row.length) <= tolerance);
    }

    // The find_matches call + the {id, label, length, part_number} option
    // shape the Length dropdowns use (Manual Lines, Port Board, Job Lines
    // edit - all through _refreshAllLengthOptions).
    async _findMatches(componentIds) {
        const matches = await this.orm.call(JOB_HOSE_LINE_MODEL, "find_matches", [componentIds]);
        return matches.map((m) => ({
            id: m.id, label: `${m.length} mm (${m.part_number})`, length: m.length, part_number: m.part_number,
        }));
    }

    // Re-queries every existing assembled Hose and Fitting Part whose BOM
    // matches this row's currently-picked Hose/Fitting1/Fitting2 (+
    // Ferrules) - Fire Wrap/Hose Guard are deliberately not part of this
    // match, they never determine which assembly gets reused. Called once whenever
    // those picks change (not on every Length keystroke - see
    // _recomputeLengthOptions for that). Race-guarded so a response for a
    // since-changed row is discarded.
    async _refreshAllLengthOptions(row) {
        row.all_length_options = [];
        row.length_options = [];
        if (!(row.hose_id && row.fitting1_id && row.fitting2_id)) {
            return;
        }
        const componentIds = [row.hose_id, row.fitting1_id, row.fitting2_id];
        if (row.ferrule1_id) componentIds.push(row.ferrule1_id);
        if (row.ferrule2_id) componentIds.push(row.ferrule2_id);
        const signature = [...componentIds].sort().join(",");

        const options = await this._findMatches(componentIds);

        const currentIds = [row.hose_id, row.fitting1_id, row.fitting2_id];
        if (row.ferrule1_id) currentIds.push(row.ferrule1_id);
        if (row.ferrule2_id) currentIds.push(row.ferrule2_id);
        if ([...currentIds].sort().join(",") !== signature) {
            return; // row's component picks changed again while this call was in flight
        }
        row.all_length_options = options;
        this._recomputeLengthOptions(row);
    }

    // create_batch payload for one row - shared by Save (Manual Lines) and
    // the Port Board's per-line create.
    _rowPayload(row) {
        return {
            job_number: this.state.jobId,
            config_id: row.config_id || false,
            hose_number: row.hose_number,
            function_id: row.function_id || false,
            description_en: row.description_en,
            description_vn: row.description_vn,
            quantity: row.quantity || 1,
            hose_id: row.hose_id,
            length: row.length,
            fitting1_id: row.fitting1_id,
            ferrule1_id: row.ferrule1_id || false,
            fitting2_id: row.fitting2_id,
            ferrule2_id: row.ferrule2_id || false,
            fire_wrap_id: row.fire_wrap_id || false,
            hose_guard_id: row.hose_guard_id || false,
            from_item_id: row.from_item_id || false,
            from_port_id: row.from_port_id || false,
            to_item_id: row.to_item_id || false,
            to_port_id: row.to_port_id || false,
            part_id: row.part_id || null,
            material_group_id: row.part_id ? null : this.state.materialGroupId,
            length_tolerance: row.length_tolerance || DEFAULT_LENGTH_TOLERANCE,
        };
    }

    // ---- Job Lines table: edit a saved line in place ----

    // Rebuilds a regular Builder row from the saved line, so the exact same
    // pick/length helpers (and the same cells as Manual Lines) edit it.
    startEditJobLine(ev, line) {
        ev.stopPropagation();
        const raw = line.raw;
        const id = (field) => (raw[field] ? raw[field][0] : false);
        const row = this._makeRow();
        row.lineId = line.id;
        row.hose_id = id("hose_id");
        row.hose_text = this.hoseOptions.find((o) => o.id === row.hose_id)?.label || line.hose;
        const cfg = row.hose_id ? this.configsByHoseId[row.hose_id] : null;
        if (cfg) {
            row.config_id = cfg.id;
            row.config_text = cfg.symbol;
            row.fitting_options = cfg.fitting_options;
            row.fire_wrap_options = cfg.fire_wrap_options;
            row.hose_guard_options = cfg.hose_guard_options;
        }
        Object.assign(row, {
            fitting1_id: id("fitting1_id"), fitting1_text: line.fitting1,
            ferrule1_id: id("ferrule1_id"), ferrule1_text: line.ferrule1,
            fitting2_id: id("fitting2_id"), fitting2_text: line.fitting2,
            ferrule2_id: id("ferrule2_id"), ferrule2_text: line.ferrule2,
            fire_wrap_id: id("fire_wrap_id"), fire_wrap_text: line.fire_wrap,
            hose_guard_id: id("hose_guard_id"), hose_guard_text: line.hose_guard,
            function_id: id("function_id"), function_text: line.function,
            hose_number: raw.hose_number || "",
            description_en: raw.description_en || "",
            description_vn: raw.description_vn || "",
            quantity: raw.quantity,
            length: raw.length,
            length_text: String(raw.length),
            part_id: id("part_id"),
            resolved_part_number: line.part_number,
        });
        this.state.editingRow = row;
        this._refreshAllLengthOptions(this.state.editingRow);
    }

    cancelEditJobLine() {
        this.state.editingRow = null;
    }

    // The server decides whether the Part Number still fits (see
    // job_hose_line.update_line) - when the edit needs a brand new one,
    // nothing is saved until the user confirms it here.
    async saveEditJobLine(confirmNewPart = false) {
        const row = this.state.editingRow;
        if (!(row.hose_id && row.fitting1_id && row.fitting2_id && row.length !== false)) {
            this.notification.add("Hose, Fitting 1, Fitting 2 and Length are required.", { type: "danger" });
            return;
        }
        const vals = {
            config_id: row.config_id || false,
            hose_number: row.hose_number,
            function_id: row.function_id || false,
            description_en: row.description_en,
            description_vn: row.description_vn,
            quantity: row.quantity || 1,
            hose_id: row.hose_id,
            length: row.length,
            fitting1_id: row.fitting1_id,
            ferrule1_id: row.ferrule1_id || false,
            fitting2_id: row.fitting2_id,
            ferrule2_id: row.ferrule2_id || false,
            fire_wrap_id: row.fire_wrap_id || false,
            hose_guard_id: row.hose_guard_id || false,
        };
        const result = await this.orm.call(JOB_HOSE_LINE_MODEL, "update_line", [[row.lineId], vals], {
            part_id: row.part_id || false,
            material_group_id: this.state.materialGroupId || false,
            length_tolerance: row.length_tolerance || DEFAULT_LENGTH_TOLERANCE,
            confirm_new_part: confirmNewPart,
        });
        if (result.status === "needs_material_group") {
            this.notification.add(
                "This change needs a new Part Number - pick a Material Group at the top first.",
                { type: "danger" }
            );
            return;
        }
        if (result.status === "needs_confirmation") {
            this.dialog.add(ConfirmationDialog, {
                title: "New Part Number",
                body: `No existing Hose and Fitting Part matches this change. ` +
                    `Create a new Part Number in Material Group "${this.state.materialGroupText}"?`,
                confirm: () => this.saveEditJobLine(true),
                cancel: () => {},
            });
            return;
        }
        this.notification.add(`Saved ${row.hose_number || "line"} (${result.part_number}).`, { type: "success" });
        this.state.editingRow = null;
        await this._loadJobLines();
        this.state.portBoardReloadToken++;
    }

    validateClientSide() {
        const errors = {};
        if (!this.state.jobId) {
            errors.job = "Select a Job Number first";
        }
        for (const row of this.state.rows) {
            if (row.status === "success" || this._isRowEmpty(row)) continue;
            if (!row.hose_id) errors[`${row._localId}_hose`] = "Pick a Hose first";
            if (!row.fitting1_id) errors[`${row._localId}_fitting1`] = "Required";
            if (!row.fitting2_id) errors[`${row._localId}_fitting2`] = "Required";
            if (row.length === false) errors[`${row._localId}_length`] = "Required";
            if (!row.part_id && !this.state.materialGroupId) {
                errors[`${row._localId}_material_group`] =
                    "No existing match picked - pick a Material Group to generate a new Part Number";
            }
        }
        this.state.errors = errors;
        return Object.keys(errors).length === 0;
    }

    async onSaveClick() {
        if (!this.validateClientSide()) {
            this.notification.add("Please fix the highlighted rows first.", { type: "danger" });
            return;
        }

        const pendingRows = this.state.rows.filter((r) => r.status !== "success" && !this._isRowEmpty(r));
        if (!pendingRows.length) {
            this.notification.add("Nothing to save.", { type: "info" });
            return;
        }

        this.state.isSaving = true;
        try {
            const payload = pendingRows.map((row) => this._rowPayload(row));

            const results = await this.orm.call(JOB_HOSE_LINE_MODEL, "create_batch", [payload]);

            results.forEach((res, i) => {
                const row = pendingRows[i];
                if (res.success) {
                    row.status = "success";
                    row.resolved_part_number = res.part_number;
                    row.errorMessage = null;
                } else {
                    row.status = "error";
                    row.errorMessage = res.error;
                }
            });

            const successCount = results.filter((r) => r.success).length;
            const failCount = results.length - successCount;

            if (successCount > 0) {
                this._loadJobLines();
                this.state.portBoardReloadToken++;
            }

            if (failCount === 0) {
                this.notification.add(`Successfully saved ${successCount} line(s).`, { type: "success" });
                this.addRow();
            } else {
                this.notification.add(
                    `${successCount} succeeded, ${failCount} failed. Please review and Save the failed rows again.`,
                    { type: "warning" }
                );
            }
        } finally {
            this.state.isSaving = false;
        }
    }
}

registry.category("actions").add("hose_fitting_manager.builder", HoseFittingBuilder);
