/** @odoo-module **/

import { Component, onWillStart, useEffect, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { PnmCombobox } from "@part_number_manager/part_management_page/pnm_combobox";

const JOB_EQUIPMENT_ITEM_MODEL = "hose_fitting_manager.job_equipment_item";
// Same value as builder.js's own DEFAULT_LENGTH_TOLERANCE - kept as a
// separate constant here rather than a shared import since this is the only
// other place a raw tolerance number is needed (narrowing lengthOptions as
// the user types, mirroring the Create List row's own Length field).
const DEFAULT_LENGTH_TOLERANCE = 100.0;

// Same resize + persist-to-localStorage convention as builder.js's own
// Create List/Job Lines tables (see its _startColumnResize) - a separate
// key/component here since this is a different table with its own columns.
const COLUMN_WIDTHS_STORAGE_KEY = "hose_fitting_manager.port_board.column_widths";
const DEFAULT_COLUMN_WIDTHS = { port: 90, toItem: 220, toPort: 130, hose: 200, length: 170 };

// A Port row's *effective* status blends the server's open/used with
// Builder's own client-side "claimed by another still-unsaved row this
// session" concept (props.reservedPortIds) - the server has no notion of
// Reserved at all (see get_port_board_data on job_equipment_item.py).
// "Used" is purely informational now - a Port can be wired more than once
// (e.g. a splitter/manifold screwed onto one Port), so it never blocks
// adding another connection; only "Reserved" (already claimed by a
// still-unsaved row from this same session) does, to avoid two drafts
// silently targeting the exact same not-yet-saved connection.
function effectiveStatus(port, reservedPortIds) {
    if (reservedPortIds.has(port.id)) {
        return "reserved";
    }
    return port.status;
}

let nextDraftId = 1;

function emptyDraft() {
    return {
        _localId: nextDraftId++,
        toItemId: false,
        toItemText: "",
        toPortId: false,
        toPortText: "",
        toPortOptions: [],
        hoseId: false,
        hoseText: "",
        length: false,
        lengthText: "",
        // Every existing assembled Part whose BOM matches the picked Hose
        // (via getLengthOptions) - lengthFilteredOptions narrows this by
        // whatever's typed, same two-tier scheme as the Create List row's
        // own all_length_options/length_options.
        lengthOptions: [],
        lengthFilteredOptions: [],
        // Set only by an explicit pick from lengthFilteredOptions - carried
        // through onAdd so Builder can reuse that exact Part instead of
        // re-deriving it, same as the grid's own row.part_id.
        lengthMatchId: false,
        lengthMatchPartNumber: "",
    };
}

export class PortBoard extends Component {
    static template = "hose_fitting_manager.PortBoard";
    static components = { PnmCombobox };
    static props = {
        jobId: [Number, Boolean],
        reservedPortIds: Object, // Set<number>
        reloadToken: Number,
        hoseOptions: Array, // [{id, label}] - same list Builder's own Hose field uses
        // (hoseId) => Promise<[{id, label, length, part_number}]> - Builder's
        // own find_matches query (see getHoseLengthOptions), resolving
        // Fitting 1/2 + Ferrules from the Hose's Config the same way
        // _pickHose does, since the Port Board never shows those fields.
        getLengthOptions: Function,
        // (fromItem, fromPort, toItem, toPort, hoseOpt, length, lengthMatch) => void
        // - Builder stages a new Create List row with all of this already
        // filled in; nothing is saved to the database from here.
        // lengthMatch is the picked lengthOptions entry, or null if the
        // user typed a custom Length instead of picking an existing match.
        onAdd: Function,
        onUsedPortClick: Function, // (jobHoseLineId) => void
    };

    setup() {
        this.orm = useService("orm");

        this.state = useState({
            items: [],
            selectedItemId: false,
            itemSearchText: "",
            // Zero or more inline "connect to" drafts per Port id - a Port
            // starts with none (see the hover "+" in port_board.xml, styled
            // like MS Word's row-insert affordance); clicking it appends a
            // fresh one, so several new lines can be staged on the same
            // Port at once (e.g. a splitter feeding more than one hose).
            // Rebuilt (new ports get an empty array, stale ports dropped)
            // on every reload - see _syncDrafts - but an in-progress port's
            // own array of drafts is never touched by that.
            connectDrafts: {},
            columnWidths: this._loadColumnWidths(),
        });

        onWillStart(() => this._reload());

        useEffect(
            () => {
                this._reload();
            },
            () => [this.props.jobId, this.props.reloadToken]
        );
    }

    async _reload() {
        if (!this.props.jobId) {
            this.state.items = [];
            this.state.selectedItemId = false;
            this.state.connectDrafts = {};
            return;
        }
        this.state.items = await this.orm.call(
            JOB_EQUIPMENT_ITEM_MODEL, "get_port_board_data", [this.props.jobId]
        );
        if (!this.state.items.some((it) => it.id === this.state.selectedItemId)) {
            this.state.selectedItemId = this.state.items[0]?.id || false;
        }
        this._syncDrafts();
    }

    // Keeps a drafts array per Port id that currently exists, without
    // wiping out drafts still being filled in on an unrelated port when the
    // board reloads (e.g. because a *different* row was just saved). A Port
    // that's never been used at all (still Open) starts with one empty
    // draft already in place - ready to type into immediately, no "+"
    // needed - but only the *first* time it's seen: once the user's own
    // "+"/trash actions have touched it, later reloads leave it alone
    // (otherwise a manually-trashed default line would keep coming back).
    _syncDrafts() {
        const livePortIds = new Set();
        for (const item of this.state.items) {
            for (const port of item.ports) {
                livePortIds.add(port.id);
                if (!(port.id in this.state.connectDrafts)) {
                    this.state.connectDrafts[port.id] =
                        effectiveStatus(port, this.props.reservedPortIds) === "open" ? [emptyDraft()] : [];
                }
            }
        }
        for (const portId of Object.keys(this.state.connectDrafts)) {
            if (!livePortIds.has(Number(portId))) {
                delete this.state.connectDrafts[portId];
            }
        }
    }

    get filteredItems() {
        const norm = this.state.itemSearchText.trim().toLowerCase();
        if (!norm) {
            return this.state.items;
        }
        return this.state.items.filter(
            (it) =>
                it.part_number.toLowerCase().includes(norm) ||
                (it.description_en || "").toLowerCase().includes(norm)
        );
    }

    get selectedItem() {
        return this.state.items.find((it) => it.id === this.state.selectedItemId) || false;
    }

    // Every other Item, as combobox options for a port's "To Item" field -
    // never the currently-selected Item itself (a Port can't connect to one
    // of its own Item's other Ports).
    get otherItemOptions() {
        return this.state.items
            .filter((it) => it.id !== this.state.selectedItemId)
            .map((it) => ({ id: it.id, label: `${it.description_en} (${it.part_number})` }));
    }

    portCounts(item) {
        let open = 0;
        let used = 0;
        for (const port of item.ports) {
            const status = effectiveStatus(port, this.props.reservedPortIds);
            if (status === "used") {
                used++;
            } else if (status === "open") {
                open++;
            }
        }
        return { open, used };
    }

    portStatus(port) {
        return effectiveStatus(port, this.props.reservedPortIds);
    }

    selectItem(itemId) {
        this.state.selectedItemId = itemId;
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

    // The hover "+" - appends one fresh draft line under this Port, ready
    // to fill in. Disabled (see the template) while the Port is Reserved,
    // same guard the old single-draft-per-port version had.
    addDraftLine(port) {
        this.state.connectDrafts[port.id].push(emptyDraft());
    }

    removeDraftLine(port, draft) {
        const drafts = this.state.connectDrafts[port.id];
        const idx = drafts.indexOf(draft);
        if (idx !== -1) {
            drafts.splice(idx, 1);
        }
    }

    canAdd(draft) {
        return !!(draft.toItemId && draft.toPortId && draft.hoseId && draft.length);
    }

    onToItemInput(draft, text) {
        draft.toItemText = text || "";
        draft.toItemId = false;
        draft.toPortId = false;
        draft.toPortText = "";
        draft.toPortOptions = [];
    }

    onToItemSelect(draft, opt) {
        draft.toItemId = opt.id;
        draft.toItemText = opt.label;
        draft.toPortId = false;
        draft.toPortText = "";
        const toItem = this.state.items.find((it) => it.id === opt.id);
        draft.toPortOptions = (toItem?.ports || [])
            .filter((p) => effectiveStatus(p, this.props.reservedPortIds) !== "reserved")
            .map((p) => ({ id: p.id, label: p.label }));
    }

    onToPortInput(draft, text) {
        draft.toPortText = text || "";
        draft.toPortId = false;
    }

    onToPortSelect(draft, opt) {
        draft.toPortId = opt.id;
        draft.toPortText = opt.label;
    }

    onHoseInput(draft, text) {
        draft.hoseText = text || "";
        draft.hoseId = false;
        draft.length = false;
        draft.lengthText = "";
        draft.lengthOptions = [];
        draft.lengthFilteredOptions = [];
        draft.lengthMatchId = false;
        draft.lengthMatchPartNumber = "";
    }

    // Picking a Hose immediately queries its matching existing Parts (same
    // BOM-match Builder's own Length field uses) - draft.length itself
    // stays blank until the user picks one of those or types a value, same
    // as the Create List row's Length field.
    async onHoseSelect(port, draft, opt) {
        draft.hoseId = opt.id;
        draft.hoseText = opt.label;
        draft.length = false;
        draft.lengthText = "";
        draft.lengthOptions = [];
        draft.lengthFilteredOptions = [];
        draft.lengthMatchId = false;
        draft.lengthMatchPartNumber = "";

        const options = await this.props.getLengthOptions(opt.id);
        // Race-guard: only apply if this draft is still around and still on
        // the Hose that was picked when the call started.
        const stillThere = (this.state.connectDrafts[port.id] || []).includes(draft);
        if (stillThere && draft.hoseId === opt.id) {
            draft.lengthOptions = options;
            draft.lengthFilteredOptions = options;
        }
    }

    onLengthInput(draft, text) {
        draft.lengthText = text || "";
        const parsed = parseFloat(text);
        draft.length = Number.isFinite(parsed) ? parsed : false;
        draft.lengthMatchId = false;
        draft.lengthMatchPartNumber = "";
        if (draft.length === false) {
            draft.lengthFilteredOptions = draft.lengthOptions;
            return;
        }
        draft.lengthFilteredOptions = draft.lengthOptions.filter(
            (o) => Math.abs(o.length - draft.length) <= DEFAULT_LENGTH_TOLERANCE
        );
    }

    onLengthSelect(draft, opt) {
        draft.length = opt.length;
        draft.lengthText = String(opt.length);
        draft.lengthMatchId = opt.id;
        draft.lengthMatchPartNumber = opt.part_number;
    }

    // Same rounding rule as the Create List row's own Length field
    // (builder.js's _roundLengthNearest) - 50mm steps under 1000mm, 100mm
    // steps from 1000mm up (e.g. 471 -> 450, not 500), so slightly
    // different typed lengths converge on the same standard value.
    _roundLengthNearest(value) {
        const step = value < 1000 ? 50 : 100;
        return Math.round(value / step) * step;
    }

    // Only runs once typing is done (on blur) and only when nothing was
    // explicitly picked from the dropdown - mirrors builder.js's own
    // onLengthBlur: round the typed value to the nearest standard
    // increment, then check whether a Part at exactly that rounded Length
    // already exists for the picked Hose's BOM - if so, silently reuse it;
    // if not, the rounded value is what gets used to generate a new Part
    // on Add.
    onLengthBlur(draft) {
        if (draft.lengthMatchId || draft.length === false) {
            return;
        }
        const rounded = this._roundLengthNearest(draft.length);
        draft.length = rounded;
        draft.lengthText = String(rounded);
        draft.lengthFilteredOptions = draft.lengthOptions.filter(
            (o) => Math.abs(o.length - rounded) <= DEFAULT_LENGTH_TOLERANCE
        );

        const exact = draft.lengthOptions.find((o) => o.length === rounded);
        if (exact) {
            draft.lengthMatchId = exact.id;
            draft.lengthMatchPartNumber = exact.part_number;
        }
    }

    onAddClick(port, draft) {
        const toItem = this.state.items.find((it) => it.id === draft.toItemId);
        const toPort = toItem.ports.find((p) => p.id === draft.toPortId);
        const lengthMatch = draft.lengthMatchId
            ? { id: draft.lengthMatchId, part_number: draft.lengthMatchPartNumber, length: draft.length }
            : null;
        this.props.onAdd(
            this.selectedItem, port, toItem, toPort,
            { id: draft.hoseId, label: draft.hoseText }, draft.length, lengthMatch
        );
        this.removeDraftLine(port, draft);
    }

    onConnectionClick(connection) {
        this.props.onUsedPortClick(connection.job_hose_line_id);
    }
}
