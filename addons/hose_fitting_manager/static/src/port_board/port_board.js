/** @odoo-module **/

import { Component, onWillStart, useEffect, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { PnmCombobox } from "@part_number_manager/part_management_page/pnm_combobox";

const JOB_EQUIPMENT_ITEM_MODEL = "hose_fitting_manager.job_equipment_item";

// Same resize + persist-to-localStorage convention as builder.js's own
// Create List/Job Lines tables (see its _startColumnResize) - a separate
// key/component here since this is a different table with its own columns.
const COLUMN_WIDTHS_STORAGE_KEY = "hose_fitting_manager.port_board.column_widths";
const DEFAULT_COLUMN_WIDTHS = {
    port: 90, toItem: 220, toPort: 130, hose: 220, length: 170,
    fitting1: 180, fitting2: 180, fireWrap: 150, hoseGuard: 150, function: 140,
};

// Same convention for the left Item list panel's own width - a single
// number rather than a per-column map, dragged via the vertical splitter
// between the two panels (see onItemsPanelResizeStart).
const ITEMS_PANEL_WIDTH_STORAGE_KEY = "hose_fitting_manager.port_board.items_panel_width";
const DEFAULT_ITEMS_PANEL_WIDTH = 320;

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

export class PortBoard extends Component {
    static template = "hose_fitting_manager.PortBoard";
    static components = { PnmCombobox };
    static props = {
        jobId: [Number, Boolean],
        reservedPortIds: Object, // Set<number>
        reloadToken: Number,
        hoseOptions: Array, // [{id, label}] - same list Builder's own Hose field uses
        functionOptions: Array, // [{id, label}] - same list Builder's own Function field uses
        // Builder's row helpers (see its rowApi) - each draft line here is a
        // regular Builder row, so Hose/Fitting/Fire Wrap/Hose Guard/Function/
        // Length behave exactly like the Manual Lines table.
        rowApi: Object,
        // Needed only when a line's Length matches no existing Part (a new
        // Part Number is generated) - picked at the top of the Builder page.
        materialGroupId: [Number, Boolean],
        // async (fromItem, fromPort, toItem, toPort, draft) => {success, error}
        // - creates the line right away (see Builder.createFromPortBoard).
        onCreate: Function,
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
            itemsPanelWidth: this._loadItemsPanelWidth(),
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
    _newDraft() {
        return {
            ...this.props.rowApi.makeRow(),
            toItemId: false,
            toItemText: "",
            toPortId: false,
            toPortText: "",
            toPortOptions: [],
            busy: false, // create call in flight - see onAddClick
            error: null, // last create error, shown under the line
        };
    }

    _syncDrafts() {
        const livePortIds = new Set();
        for (const item of this.state.items) {
            for (const port of item.ports) {
                livePortIds.add(port.id);
                if (!(port.id in this.state.connectDrafts)) {
                    this.state.connectDrafts[port.id] =
                        effectiveStatus(port, this.props.reservedPortIds) === "open" ? [this._newDraft()] : [];
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

    // Compact "used/total" count for the Item list - status here is the
    // Port's raw backend status (a Port is "used" the moment it has at
    // least one real, saved connection - see get_port_board_data), not the
    // client-only Reserved concept, since the warning icon below is about
    // real, saved wiring gaps, not this session's still-unsaved drafts.
    portCounts(item) {
        const total = item.ports.length;
        const used = item.ports.filter((p) => p.status === "used").length;
        return { used, total };
    }

    // Badge color for the Item list's "used/total" count: blue when nothing
    // is connected yet, red while partially wired (still needs attention),
    // green once every Port has a connection.
    portCountBadgeClass(item) {
        const { used, total } = this.portCounts(item);
        if (used === 0) {
            return "text-bg-primary";
        }
        if (used < total) {
            return "text-bg-danger";
        }
        return "text-bg-success";
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

    _loadItemsPanelWidth() {
        const saved = parseInt(localStorage.getItem(ITEMS_PANEL_WIDTH_STORAGE_KEY), 10);
        return Number.isFinite(saved) ? saved : DEFAULT_ITEMS_PANEL_WIDTH;
    }

    _saveItemsPanelWidth() {
        try {
            localStorage.setItem(ITEMS_PANEL_WIDTH_STORAGE_KEY, String(this.state.itemsPanelWidth));
        } catch {
            // storage unavailable - width just won't be remembered next time
        }
    }

    onItemsPanelResizeStart(ev) {
        ev.preventDefault();
        const startX = ev.clientX;
        const startWidth = this.state.itemsPanelWidth;
        const onMouseMove = (moveEv) => {
            this.state.itemsPanelWidth = Math.max(180, startWidth + (moveEv.clientX - startX));
        };
        const onMouseUp = () => {
            window.removeEventListener("mousemove", onMouseMove);
            window.removeEventListener("mouseup", onMouseUp);
            this._saveItemsPanelWidth();
        };
        window.addEventListener("mousemove", onMouseMove);
        window.addEventListener("mouseup", onMouseUp);
    }

    // Column widths are kept as relative weights and rendered as a share of
    // the table's width (the Action column is a fixed 76px), so every column
    // fits on screen without a horizontal scrollbar - dragging a column still
    // works, it just shifts its share against the others.
    columnStyle(columnKey) {
        const widths = this.state.columnWidths;
        const total = Object.keys(DEFAULT_COLUMN_WIDTHS).reduce((sum, key) => sum + widths[key], 0);
        return `width: ${((widths[columnKey] / total) * 100).toFixed(2)}%`;
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
        this.state.connectDrafts[port.id].push(this._newDraft());
    }

    removeDraftLine(port, draft) {
        const drafts = this.state.connectDrafts[port.id];
        const idx = drafts.indexOf(draft);
        if (idx !== -1) {
            drafts.splice(idx, 1);
        }
    }

    // Everything a line needs except a Material Group - which only matters
    // when no existing Part matches the Length (see missingMaterialGroup).
    _isComplete(draft) {
        return !!(draft.toItemId && draft.toPortId && draft.hose_id &&
            draft.fitting1_id && draft.fitting2_id && draft.length !== false);
    }

    missingMaterialGroup(draft) {
        return this._isComplete(draft) && !draft.part_id && !this.props.materialGroupId;
    }

    canAdd(draft) {
        return this._isComplete(draft) && !this.missingMaterialGroup(draft) && !draft.busy;
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

    async onAddClick(port, draft) {
        const toItem = this.state.items.find((it) => it.id === draft.toItemId);
        const toPort = toItem.ports.find((p) => p.id === draft.toPortId);
        draft.busy = true;
        draft.error = null;
        try {
            const result = await this.props.onCreate(this.selectedItem, port, toItem, toPort, draft);
            if (result.success) {
                this.removeDraftLine(port, draft);
            } else {
                draft.error = result.error;
            }
        } finally {
            draft.busy = false;
        }
    }

    onConnectionClick(connection) {
        this.props.onUsedPortClick(connection.job_hose_line_id);
    }
}
