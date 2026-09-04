/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { PnmCombobox } from "./pnm_combobox";

const PART_NUMBER_MODEL = "part_number_manager.part_number";
// Vendor (res.partner) and Part Number are unbounded, ever-growing tables -
// preloading them whole (like the small reference lists below) gets slower
// every time someone adds a Vendor or Part. Instead they're searched live
// against the server as the user types, same idea as Odoo's own Many2one.
const SEARCH_DEBOUNCE_MS = 300;
const SEARCH_LIMIT = 20;
const COLUMN_WIDTHS_STORAGE_KEY = "part_number_manager.part_management_page.column_widths";
const ACTIVE_TAB_STORAGE_KEY = "part_number_manager.part_management_page.active_tab";
const COLUMN_VISIBILITY_STORAGE_KEY = "part_number_manager.part_management_page.column_visibility";
const RECENT_PARTS_STORAGE_KEY = "part_number_manager.part_management_page.recent_parts";
const RECENT_COLUMN_WIDTHS_STORAGE_KEY = "part_number_manager.part_management_page.recent_column_widths";
const DEFAULT_RECENT_COLUMN_WIDTHS = {
    material_group: 130,
    part_number: 120,
    job_number: 120,
    short_description: 180,
    long_description: 220,
    part_type: 130,
    vendor: 150,
    vendor_ref: 120,
    make_buy: 90,
    time: 100,
};
const DEFAULT_COLUMN_WIDTHS = {
    legacy: 180,
    material_group: 180,
    part_number: 140,
    job_number: 140,
    short_description: 200,
    long_description: 240,
    part_type: 180,
    vendor: 180,
    vendor_ref: 130,
    make_buy: 110,
};

// Toggleable columns offered by the "Columns" picker - key must match the
// <col>/<th>/<td> t-if guards below. "legacy" only ever shows on the
// Convert tab (see the template's own t-if on top of this), so it's simply
// left out of the picker while the Create tab is active rather than given
// its own tab-conditional entry here.
const TOGGLEABLE_COLUMNS = [
    { key: "legacy", label: "Old Part Number", convertOnly: true },
    { key: "material_group", label: "Material Group" },
    { key: "job_number", label: "Job Number" },
    { key: "short_description", label: "Short Description" },
    { key: "long_description", label: "Long Description" },
    { key: "part_type", label: "Part Type" },
    { key: "vendor", label: "Vendor" },
    { key: "vendor_ref", label: "Vendor Reference" },
    { key: "make_buy", label: "Make/Buy" },
];

export class PartManagementPage extends Component {
    static template = "part_number_manager.PartManagementPage";
    static components = { PnmCombobox };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.action = useService("action");

        this.state = useState({
            activeTab: this._loadActiveTab(), // "create" | "convert"
            rows: [],
            errors: {},
            isSaving: false,
            columnWidths: this._loadColumnWidths(),
            columnVisibility: this._loadColumnVisibility(),
            showColumnPicker: false,
            // Live search results for Vendor / Part Number fields - see
            // SEARCH_DEBOUNCE_MS comment above. Empty until the user types.
            vendorOptions: [],
            partOptions: [],
            // Every successfully created/converted part this session, newest
            // first - a running log below the working table so a user who
            // just saved a batch can scroll back and re-open any of them,
            // even after the row itself scrolls out of view or a new blank
            // row gets added on top.
            recentParts: this._loadRecentParts(),
            recentColumnWidths: this._loadRecentColumnWidths(),
        });

        // Each *Options array is the source list for one PnmCombobox field:
        // [{id, label}]. Material Group / Job Number / Part Type are small,
        // bounded catalog/config lists - fine to preload whole. Vendor and
        // Part Number are not (see SEARCH_DEBOUNCE_MS comment) - those live
        // in state.vendorOptions/state.partOptions instead, filled in by
        // _searchVendors/_searchParts as the user types.
        this.materialGroupOptions = [];
        this.jobNumberOptions = [];
        this.partTypeOptions = [];
        this.partTypes = [];
        this.attributeDefs = {}; // attribute_id -> {name, value_type, uom, options}
        this._searchTimers = {};

        onWillStart(async () => {
            await Promise.all([
                this._loadMaterialGroups(),
                this._loadJobNumbers(),
                this._loadPartTypesAndAttributes(),
            ]);
            this.addRow();
        });
    }

    // Debounces one named live-search field (e.g. "vendor", "part") so a
    // burst of keystrokes fires one RPC after typing pauses, not one per
    // keystroke.
    _debouncedSearch(key, fn) {
        clearTimeout(this._searchTimers[key]);
        this._searchTimers[key] = setTimeout(fn, SEARCH_DEBOUNCE_MS);
    }

    async _loadMaterialGroups() {
        // Not scoped to/grouped by Main Category: a group with no Category
        // set yet (an older row never backfilled) must still show up here.
        const groups = await this.orm.searchRead(
            "part_number_manager.material_group", [], ["code", "description"]
        );
        this.materialGroupOptions = groups.map((g) => ({ id: g.id, label: `${g.code} - ${g.description}` }));
    }

    async _loadJobNumbers() {
        const jobs = await this.orm.searchRead("project.project", [], ["name"]);
        this.jobNumberOptions = jobs.filter((j) => j.name).map((j) => ({ id: j.id, label: j.name }));
    }

    async _searchVendors(text) {
        const domain = text ? [["name", "ilike", text]] : [];
        const vendors = await this.orm.searchRead("res.partner", domain, ["name"], { limit: SEARCH_LIMIT });
        this.state.vendorOptions = vendors.filter((v) => v.name).map((v) => ({ id: v.id, label: v.name }));
    }

    async _loadPartTypesAndAttributes() {
        this.partTypes = await this.orm.searchRead(
            "part_number_manager.part_type", [], ["name", "attribute_ids"]
        );
        this.partTypeOptions = this.partTypes.map((t) => ({ id: t.id, label: t.name }));
        const attributeIds = [...new Set(this.partTypes.flatMap((t) => t.attribute_ids))];
        if (!attributeIds.length) {
            return;
        }
        const attributes = await this.orm.read(
            "part_number_manager.part_attribute", attributeIds, ["name", "value_type", "uom"]
        );
        const options = await this.orm.searchRead(
            "part_number_manager.part_attribute_option",
            [["attribute_id", "in", attributeIds]],
            ["name", "attribute_id"]
        );
        for (const attr of attributes) {
            this.attributeDefs[attr.id] = {
                name: attr.name,
                value_type: attr.value_type,
                uom: attr.uom,
                options: options.filter((o) => o.attribute_id[0] === attr.id),
            };
        }
    }

    // Shared live search backing both the Old Part Number and Target Part
    // comboboxes - both search the same Part Number model, just filtered
    // differently afterwards (see legacyOptions/getTargetOptions below).
    // `materialGroupId` narrows the query itself (not just the client-side
    // filter) so the Target Part search - which only ever wants matches in
    // the row's own Material Group - doesn't waste its SEARCH_LIMIT results
    // on parts from other groups. Old Part Number search omits it: any
    // Material Group is a valid legacy code to convert (see legacyOptions).
    async _searchParts(text, materialGroupId) {
        const domain = [];
        if (text) {
            domain.push(["part_number", "ilike", text]);
        }
        if (materialGroupId) {
            domain.push(["material_group_id", "=", materialGroupId]);
        }
        const parts = await this.orm.searchRead(
            PART_NUMBER_MODEL,
            domain,
            ["part_number", "material_group_id", "state", "short_description", "long_description"],
            { limit: SEARCH_LIMIT }
        );
        // Records without a part_number yet (e.g. a draft saved from the
        // classic form before Generate ever ran) have nothing meaningful to
        // autocomplete against - drop them instead of shipping a broken
        // (non-string) label into the datalist.
        this.state.partOptions = parts
            .filter((p) => p.part_number)
            .map((p) => ({
                id: p.id,
                label: p.part_number,
                material_group_id: p.material_group_id ? p.material_group_id[0] : false,
                state: p.state,
                short_description: p.short_description || "",
                long_description: p.long_description || "",
            }));
    }

    // Any part can be picked as the "Legacy Part Number" to convert -
    // regardless of Material Group (legacy codes predate the current
    // group/format rules, see techspec 2.2) and regardless of state: the
    // mapping is N-N, so an already-obsolete legacy code (superseded once
    // already) must stay pickable for a *second* new code pointing at it.
    // Excluding obsolete parts here would make the autocomplete miss it on
    // the second conversion and try to re-create it, hitting the
    // part_number unique constraint.
    get legacyOptions() {
        return this.state.partOptions;
    }

    // Bug fix: the template refers to this as a plain component getter
    // (like legacyOptions above), not to state.vendorOptions directly.
    get vendorOptions() {
        return this.state.vendorOptions;
    }

    // Candidates for "attach to an existing Part Number" are scoped to the
    // row's own Material Group, and exclude the legacy part itself and any
    // already-obsolete part.
    getTargetOptions(row) {
        return this.state.partOptions.filter((p) =>
            p.state !== "obsolete" &&
            p.material_group_id === row.material_group_id &&
            p.id !== row.conversion_legacy_id
        );
    }

    // Resolves free-typed text against a datalist's options by exact
    // (case-insensitive) label match. Anything else - partial text, a typo,
    // an empty string - resolves to `false` ("no selection"), which is
    // exactly what callers want: only a full match counts as a pick.
    resolveIdByLabel(options, text) {
        const norm = (text || "").trim().toLowerCase();
        if (!norm) {
            return false;
        }
        const match = options.find((o) => String(o.label || "").toLowerCase() === norm);
        return match ? match.id : false;
    }

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
            // Private browsing / storage disabled / quota - column widths
            // just won't be remembered next time, nothing else depends on it.
        }
    }

    _todayKey() {
        return new Date().toDateString(); // e.g. "Thu Aug 27 2026" - day-granularity only
    }

    // Kept until the end of the calendar day (client-local), then dropped -
    // a stale list from a previous day would just be confusing noise, not
    // useful history (that's what the All Part Numbers list is for).
    _loadRecentParts() {
        try {
            const saved = JSON.parse(localStorage.getItem(RECENT_PARTS_STORAGE_KEY) || "null");
            if (saved && saved.day === this._todayKey() && Array.isArray(saved.parts)) {
                return saved.parts;
            }
        } catch {
            // Corrupt/unreadable - start fresh below.
        }
        return [];
    }

    _saveRecentParts() {
        try {
            localStorage.setItem(RECENT_PARTS_STORAGE_KEY, JSON.stringify({
                day: this._todayKey(),
                parts: this.state.recentParts,
            }));
        } catch {
            // Private browsing / storage disabled / quota - just won't
            // survive a refresh this time, nothing else depends on it.
        }
    }

    _loadRecentColumnWidths() {
        let saved = {};
        try {
            saved = JSON.parse(localStorage.getItem(RECENT_COLUMN_WIDTHS_STORAGE_KEY) || "{}");
        } catch {
            saved = {};
        }
        return { ...DEFAULT_RECENT_COLUMN_WIDTHS, ...saved };
    }

    _saveRecentColumnWidths() {
        try {
            localStorage.setItem(RECENT_COLUMN_WIDTHS_STORAGE_KEY, JSON.stringify(this.state.recentColumnWidths));
        } catch {
            // Not remembered this time - not fatal, columns just default back next visit.
        }
    }

    onRecentColumnResizeStart(columnKey, ev) {
        ev.preventDefault();
        const startX = ev.clientX;
        const startWidth = this.state.recentColumnWidths[columnKey];
        const onMouseMove = (moveEv) => {
            this.state.recentColumnWidths[columnKey] = Math.max(60, startWidth + (moveEv.clientX - startX));
        };
        const onMouseUp = () => {
            window.removeEventListener("mousemove", onMouseMove);
            window.removeEventListener("mouseup", onMouseUp);
            this._saveRecentColumnWidths();
        };
        window.addEventListener("mousemove", onMouseMove);
        window.addEventListener("mouseup", onMouseUp);
    }

    _loadActiveTab() {
        try {
            const saved = localStorage.getItem(ACTIVE_TAB_STORAGE_KEY);
            return saved === "convert" ? "convert" : "create";
        } catch {
            return "create";
        }
    }

    _saveActiveTab() {
        try {
            localStorage.setItem(ACTIVE_TAB_STORAGE_KEY, this.state.activeTab);
        } catch {
            // Not remembered this time - not fatal, tab just defaults to
            // Create New next visit.
        }
    }

    _loadColumnVisibility() {
        let saved = {};
        try {
            saved = JSON.parse(localStorage.getItem(COLUMN_VISIBILITY_STORAGE_KEY) || "{}");
        } catch {
            saved = {};
        }
        const visibility = {};
        for (const col of TOGGLEABLE_COLUMNS) {
            visibility[col.key] = saved[col.key] !== false;
        }
        return visibility;
    }

    _saveColumnVisibility() {
        try {
            localStorage.setItem(COLUMN_VISIBILITY_STORAGE_KEY, JSON.stringify(this.state.columnVisibility));
        } catch {
            // Not remembered this time - columns just default back to shown.
        }
    }

    toggleColumnPicker() {
        this.state.showColumnPicker = !this.state.showColumnPicker;
    }

    toggleColumnVisibility(key) {
        this.state.columnVisibility[key] = !this.state.columnVisibility[key];
        this._saveColumnVisibility();
    }

    // The columns actually offered in the picker for the current tab -
    // "legacy" only makes sense (and only renders) on the Convert tab.
    get toggleableColumns() {
        return TOGGLEABLE_COLUMNS.filter((c) => !c.convertOnly || this.state.activeTab === "convert");
    }

    // Drag-to-resize for the table's <colgroup> widths, persisted to
    // localStorage so it's remembered across visits (same idea as
    // jacon_core's resizable_column_list_view.js for standard list views -
    // this page's table is hand-built, not a standard List View, so it
    // needs its own small version of the same behavior).
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

    async copyCell(text) {
        if (!text) {
            return;
        }
        try {
            await navigator.clipboard.writeText(String(text));
            this.notification.add("Copied to clipboard.", { type: "success" });
        } catch {
            this.notification.add("Could not copy to clipboard.", { type: "danger" });
        }
    }

    async openPart(id) {
        await this.action.doAction({
            type: "ir.actions.act_window",
            res_model: PART_NUMBER_MODEL,
            res_id: id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    switchTab(tab) {
        this.state.activeTab = tab;
        this._saveActiveTab();
        if (!this.state.rows.some((r) => r.status !== "success")) {
            this.addRow();
        }
    }

    _makeRowRaw() {
        return {
            _localId: Date.now() + Math.random(),
            material_group_id: false,
            material_group_text: "", // displayed text of the Material Group cell (see job_number_text)
            job_number: false,
            job_number_text: "", // displayed text of the Job Number cell - kept in sync so a
                                  // paste-resolved value actually shows up, not just its id
            short_description: "",
            long_description: "",
            vendor_id: false,
            vendor_text: "", // displayed Vendor text; also the name to create-on-Save when unmatched
            vendor_ref: "",
            part_type_id: false,
            part_type_text: "", // displayed text of the Part Type cell (see job_number_text)
            make_buy: false,
            attributes: [],
            conversion_legacy_id: false,
            legacyText: "", // displayed text of the Old Part Number cell (see job_number_text)
            legacyCodeText: "", // typed legacy code with no match - will be created on Save
            existing_new_part_id: false, // (convert tab only) resolved match, if any
            targetPartText: "", // (convert tab only) raw typed text - blank means "generate a new one"
            status: "pending", // pending | success | error
            resultPartNumber: null,
            errorMessage: null,
        };
    }

    // Bulk creation is usually all for the same Job - carry the first row's
    // Job Number forward onto any freshly made row so it doesn't need
    // retyping on every row, whether it's added via the Add Row button or
    // as an overflow row while pasting a multi-row clipboard block (see
    // onCellPaste below - it calls this directly, not addRow()).
    _makeRow() {
        const row = this._makeRowRaw();
        const firstRow = this.state.rows[0];
        if (firstRow && firstRow.job_number) {
            row.job_number = firstRow.job_number;
            row.job_number_text = firstRow.job_number_text;
        }
        return row;
    }

    addRow() {
        this.state.rows.push(this._makeRow());
    }

    removeRow(localId) {
        this.state.rows = this.state.rows.filter((r) => r._localId !== localId);
    }

    // Type-to-filter against the flat Material Group list, not scoped to
    // Main Category - a group with no Category set yet (e.g. an older row
    // never backfilled) must still be reachable. allowCreate=false on the
    // combobox means any text that isn't an exact match gets discarded on
    // blur (see PnmCombobox) - never silently accepted as-is.
    _setMaterialGroupText(row, text) {
        row.material_group_text = text || "";
        const match = this.materialGroupOptions.find(
            (o) => o.label.toLowerCase() === (text || "").trim().toLowerCase()
        );
        this._setMaterialGroup(row, match ? match.id : false);
    }

    _setMaterialGroup(row, materialGroupId) {
        row.material_group_id = materialGroupId;
        // The target-part datalist is scoped to this Material Group - clear
        // a stale pick if the group changed underneath it.
        row.existing_new_part_id = false;
        row.targetPartText = "";
        if (materialGroupId && this.state.activeTab === "convert") {
            this._debouncedSearch("part", () => this._searchParts("", materialGroupId));
        }
    }

    // Job Number is search-only against existing Projects - never created on
    // the fly here (unlike Old Part Number/Vendor below) - so an unmatched
    // text is discarded on blur by the combobox (allowCreate=false), same
    // as Material Group.
    _setJobNumberText(row, text) {
        row.job_number_text = text || "";
        row.job_number = this.resolveIdByLabel(this.jobNumberOptions, text);
    }

    // Vendor allows creating on the fly, like Old Part Number: an unmatched
    // name is kept as vendor_text and sent to the server as vendor_name, to
    // be find-or-created there (see create_batch_with_generated_number).
    _setVendorText(row, text) {
        row.vendor_text = text || "";
        row.vendor_id = this.resolveIdByLabel(this.state.vendorOptions, text);
        // A part with a Vendor name set is being bought, not made in-house -
        // same rule as the classic form's onchange. Only flips forward to
        // Buy; clearing the Vendor doesn't revert it.
        if (row.vendor_text) {
            row.make_buy = "buy";
        }
        this._debouncedSearch("vendor", () => this._searchVendors(row.vendor_text));
    }

    onAttributeValueChange(attr, value) {
        attr.value = value;
    }

    onMakeBuyChange(row, ev) {
        row.make_buy = ev.target.value || false;
    }

    _setPartTypeText(row, text) {
        row.part_type_text = text || "";
        this._setPartType(row, this.resolveIdByLabel(this.partTypeOptions, text));
    }

    _setPartType(row, partTypeId) {
        row.part_type_id = partTypeId;
        if (!partTypeId) {
            row.attributes = [];
            return;
        }
        const partType = this.partTypes.find((t) => t.id === partTypeId);
        row.attributes = (partType ? partType.attribute_ids : []).map((attributeId) => {
            const def = this.attributeDefs[attributeId] || {};
            return {
                attribute_id: attributeId,
                name: def.name || "",
                value_type: def.value_type || "char",
                uom: def.uom || "",
                options: def.options || [],
                value: "",
            };
        });
    }

    // Old Part Number allows creating on the fly: unmatched text is kept as
    // pending "create" text instead of being discarded. Picking an existing
    // one auto-fills every field it already has data for - Material Group,
    // Job Number, Description, Vendor/Vendor Reference, Part Type (+ its
    // Attribute values), Make/Buy - so none of it has to be retyped for the
    // converted part. Fetched fresh per pick (not from the lightweight
    // `allParts` list used for the autocomplete itself, which only carries
    // the few fields that list needs) since this only ever needs to run
    // once, right when a match is actually chosen.
    _setLegacyPart(row, text) {
        const raw = text || "";
        row.legacyText = raw;
        const id = this.resolveIdByLabel(this.legacyOptions, raw);
        row.conversion_legacy_id = id;
        row.legacyCodeText = id ? "" : raw.trim();
        if (id) {
            this._applyLegacyPartDetails(row, id);
        } else {
            // Cleared, or typed over an old match without a new one (yet) -
            // don't leave the previous pick's auto-filled fields sitting
            // there looking like they still apply to nothing.
            this._clearLegacyAutofill(row);
        }
        this._debouncedSearch("part", () => this._searchParts(raw));
    }

    _clearLegacyAutofill(row) {
        row.material_group_text = "";
        this._setMaterialGroup(row, false);
        row.job_number = false;
        row.job_number_text = "";
        row.vendor_id = false;
        row.vendor_text = "";
        row.vendor_ref = "";
        row.part_type_text = "";
        this._setPartType(row, false);
        row.make_buy = false;
        row.short_description = "";
        row.long_description = "";
    }

    async _applyLegacyPartDetails(row, legacyId) {
        const [legacy] = await this.orm.read(PART_NUMBER_MODEL, [legacyId], [
            "material_group_id", "job_number", "short_description", "long_description",
            "vendor_id", "vendor_ref", "part_type_id", "make_buy", "attribute_value_ids",
        ]);
        // The row may have been pointed at a different Old Part Number (or
        // cleared) again by the time this resolves - only apply if it's
        // still the pick this fetch was for.
        if (!legacy || row.conversion_legacy_id !== legacyId) {
            return;
        }

        row.short_description = legacy.short_description || "";
        row.long_description = legacy.long_description || "";
        row.vendor_ref = legacy.vendor_ref || "";
        if (legacy.make_buy) {
            row.make_buy = legacy.make_buy;
        }
        if (legacy.material_group_id) {
            this._setMaterialGroup(row, legacy.material_group_id[0]);
            row.material_group_text = legacy.material_group_id[1];
        }
        if (legacy.job_number) {
            row.job_number = legacy.job_number[0];
            row.job_number_text = legacy.job_number[1];
        }
        if (legacy.vendor_id) {
            row.vendor_id = legacy.vendor_id[0];
            row.vendor_text = legacy.vendor_id[1];
        }
        if (legacy.part_type_id) {
            row.part_type_text = legacy.part_type_id[1];
            this._setPartType(row, legacy.part_type_id[0]);
            if (legacy.attribute_value_ids.length) {
                const values = await this.orm.read(
                    "part_number_manager.part_attribute_value", legacy.attribute_value_ids,
                    ["attribute_id", "value_char", "value_float", "value_option_id"]
                );
                for (const attr of row.attributes) {
                    const match = values.find((v) => v.attribute_id[0] === attr.attribute_id);
                    if (!match) {
                        continue;
                    }
                    if (attr.value_type === "float") {
                        attr.value = match.value_float || match.value_float === 0 ? String(match.value_float) : "";
                    } else if (attr.value_type === "selection") {
                        attr.value = match.value_option_id ? match.value_option_id[1] : "";
                    } else {
                        attr.value = match.value_char || "";
                    }
                }
            }
        }
    }

    // Leaving this blank means "generate a new Part Number" (handled
    // server-side, same as the Create New flow). Typing something is only
    // ever a pick from existing Part Numbers - a typo/no-match is an error,
    // it never silently falls back to generating an unrelated new part.
    _setTargetPart(row, text) {
        row.targetPartText = (text || "").trim();
        row.existing_new_part_id = this.resolveIdByLabel(this.getTargetOptions(row), text);
        this._debouncedSearch("part", () => this._searchParts(row.targetPartText, row.material_group_id));
    }

    // Column order of each tab's editable cells, left to right, exactly as
    // laid out in the table - used to figure out which field a pasted
    // block's 2nd/3rd/... column lands on (see onCellPaste below).
    // "skip" marks the Create tab's Part Number column, which has no input
    // (it's assigned on Save) - a paste that reaches it is simply dropped.
    get columnOrder() {
        return this.state.activeTab === "convert"
            ? ["legacy", "material_group_id", "target_part", "job_number", "short_description",
               "long_description", "part_type_id", "vendor_id", "vendor_ref", "make_buy"]
            : ["material_group_id", "skip", "job_number", "short_description",
               "long_description", "part_type_id", "vendor_id", "vendor_ref", "make_buy"];
    }

    _applyPastedCell(row, columnKey, text) {
        switch (columnKey) {
            case "legacy":
                this._setLegacyPart(row, text);
                break;
            case "material_group_id":
                this._setMaterialGroupText(row, text);
                break;
            case "target_part":
                this._setTargetPart(row, text);
                break;
            case "job_number":
                this._setJobNumberText(row, text);
                break;
            case "short_description":
                row.short_description = (text || "").trim();
                break;
            case "long_description":
                row.long_description = (text || "").trim();
                break;
            case "part_type_id":
                this._setPartTypeText(row, text);
                break;
            case "vendor_id":
                this._setVendorText(row, text);
                break;
            case "vendor_ref":
                row.vendor_ref = (text || "").trim();
                break;
            case "make_buy": {
                const norm = (text || "").trim().toLowerCase();
                if (norm === "make" || norm === "buy") {
                    row.make_buy = norm;
                }
                break;
            }
            // "skip" (and anything past the last column): nothing to fill.
        }
    }

    // Lets a block copied straight out of Excel/Sheets be pasted starting at
    // whichever cell the cursor is in, landing each pasted column on the
    // matching field to its right (per `columnOrder`) and each pasted line
    // on the next row *downward* - filling into rows that already exist
    // first, exactly like pasting a multi-cell selection into Excel, which
    // overwrites whatever's already below rather than inserting new rows in
    // the middle. A brand new row is only added once there's no existing
    // row left to fill. Already-saved rows (status "success") are skipped
    // over rather than overwritten - they're locked/disabled in the UI for
    // the same reason. A plain single-cell paste (no tab, no newline) is
    // left alone so normal typing/paste into one field keeps working
    // exactly as before.
    onCellPaste(row, columnKey, ev) {
        const text = (ev.clipboardData || window.clipboardData).getData("text");
        if (!text || !/[\t\r\n]/.test(text)) {
            return;
        }
        ev.preventDefault();

        const lines = text.split(/\r\n|\r|\n/).filter((line) => line !== "");
        if (!lines.length) {
            return;
        }
        const parsedLines = lines.map((line) => line.split("\t"));

        const columnOrder = this.columnOrder;
        const startIndex = columnOrder.indexOf(columnKey);
        if (startIndex === -1) {
            return;
        }

        const applyLine = (targetRow, cols) => {
            cols.forEach((cellText, i) => {
                const key = columnOrder[startIndex + i];
                if (key) {
                    this._applyPastedCell(targetRow, key, cellText);
                }
            });
        };

        let cursor = this.state.rows.indexOf(row);
        for (const cols of parsedLines) {
            while (cursor < this.state.rows.length && this.state.rows[cursor].status === "success") {
                cursor++;
            }
            const targetRow = cursor < this.state.rows.length ? this.state.rows[cursor] : this._makeRow();
            if (cursor >= this.state.rows.length) {
                this.state.rows.push(targetRow);
            }
            applyLine(targetRow, cols);
            cursor++;
        }
    }

    validateClientSide() {
        const errors = {};
        for (const row of this.state.rows) {
            if (row.status === "success") continue;
            if (!row.material_group_id) errors[`${row._localId}_group`] = "Required";
            if (this.state.activeTab === "create" && !row.job_number) {
                errors[`${row._localId}_job`] = "Required";
            }
            if (!row.make_buy) {
                errors[`${row._localId}_make_buy`] = "Required";
            }
            if (this.state.activeTab === "convert") {
                if (!row.conversion_legacy_id && !row.legacyCodeText) {
                    errors[`${row._localId}_legacy`] = "Type or pick an Old Part Number to convert";
                }
                if (row.targetPartText && !row.existing_new_part_id) {
                    errors[`${row._localId}_target`] = "This Part Number does not exist";
                }
            }
        }
        this.state.errors = errors;
        return Object.keys(errors).length === 0;
    }

    // Only unsaved/failed rows are sent - rows already saved stay put and are
    // never resent, so clicking Save again can't create duplicates.
    async onSaveClick() {
        if (!this.validateClientSide()) {
            this.notification.add("Please fix the highlighted rows first.", { type: "danger" });
            return;
        }

        const pendingRows = this.state.rows.filter((r) => r.status !== "success");
        if (!pendingRows.length) {
            this.notification.add("Nothing to save.", { type: "info" });
            return;
        }

        this.state.isSaving = true;
        try {
            const payload = pendingRows.map((row) => ({
                material_group_id: row.material_group_id,
                job_number: row.job_number || false,
                short_description: row.short_description,
                long_description: row.long_description,
                vendor_id: row.vendor_id || false,
                // Unmatched Vendor text is find-or-created server-side, same
                // idea as an unmatched Old Part Number.
                vendor_name: row.vendor_id ? null : ((row.vendor_text || "").trim() || null),
                vendor_ref: row.vendor_ref,
                part_type_id: row.part_type_id || false,
                make_buy: row.make_buy || false,
                attribute_values: row.attributes
                    .filter((a) => a.value)
                    .map((a) => ({ attribute_id: a.attribute_id, value: a.value })),
                conversion_legacy_id: row.conversion_legacy_id || null,
                conversion_legacy_text: row.conversion_legacy_id ? null : (row.legacyCodeText || null),
                existing_new_part_id: row.existing_new_part_id || null,
                target_part_text: row.existing_new_part_id ? null : (row.targetPartText || null),
            }));

            const results = await this.orm.call(
                PART_NUMBER_MODEL, "create_batch_with_generated_number", [payload]
            );

            results.forEach((res, i) => {
                const row = pendingRows[i];
                if (res.success) {
                    row.status = "success";
                    row.resultPartNumber = res.part_number;
                    row.errorMessage = null;
                    this.state.recentParts.unshift({
                        id: res.part_id,
                        part_number: res.part_number,
                        material_group_label: row.material_group_text,
                        job_number_label: row.job_number_text,
                        short_description: row.short_description,
                        long_description: row.long_description,
                        part_type_label: row.part_type_text,
                        vendor_label: row.vendor_text,
                        vendor_ref: row.vendor_ref,
                        make_buy: row.make_buy,
                        time: new Date().toLocaleTimeString(),
                    });
                } else {
                    row.status = "error";
                    row.errorMessage = res.error;
                }
            });
            this._saveRecentParts();

            // No manual refresh needed here anymore: Vendor and Part Number
            // are searched live against the server (see SEARCH_DEBOUNCE_MS
            // comment above), so the next search on either field already
            // picks up anything just created.

            const successCount = results.filter((r) => r.success).length;
            const failCount = results.length - successCount;

            if (failCount === 0) {
                this.notification.add(`Successfully created ${successCount} part(s).`, { type: "success" });
                this.addRow();
            } else {
                this.notification.add(
                    `${successCount} succeeded, ${failCount} failed. ` +
                    `Please review and Save the failed rows again.`,
                    { type: "warning" }
                );
            }
        } finally {
            this.state.isSaving = false;
        }
    }
}

registry.category("actions").add("part_number_manager.part_management_page", PartManagementPage);
