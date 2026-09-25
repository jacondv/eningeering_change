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

// A Port row's *effective* status blends the server's open/used with
// Builder's own client-side "claimed by another still-unsaved row this
// session" concept (props.reservedPortIds) - the server has no notion of
// Reserved at all (see get_port_board_data on job_equipment_item.py).
function effectiveStatus(port, reservedPortIds) {
    if (port.status === "open" && reservedPortIds.has(port.id)) {
        return "reserved";
    }
    return port.status;
}

function emptyDraft() {
    return {
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
            // One inline "connect to" draft per Open port id - lets several
            // ports on the same Item be mid-fill at once without clobbering
            // each other. Rebuilt (new entries added, stale ones dropped) on
            // every reload - see _syncDrafts.
            connectDrafts: {},
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

    // Keeps one draft per Port id that currently exists, without wiping out
    // a draft still being filled in on an unrelated port when the board
    // reloads (e.g. because a *different* row was just saved).
    _syncDrafts() {
        const livePortIds = new Set();
        for (const item of this.state.items) {
            for (const port of item.ports) {
                livePortIds.add(port.id);
                if (!(port.id in this.state.connectDrafts)) {
                    this.state.connectDrafts[port.id] = emptyDraft();
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

    canAdd(port) {
        const draft = this.state.connectDrafts[port.id];
        return !!(draft && draft.toItemId && draft.toPortId && draft.hoseId && draft.length);
    }

    onToItemInput(port, text) {
        const draft = this.state.connectDrafts[port.id];
        draft.toItemText = text || "";
        draft.toItemId = false;
        draft.toPortId = false;
        draft.toPortText = "";
        draft.toPortOptions = [];
    }

    onToItemSelect(port, opt) {
        const draft = this.state.connectDrafts[port.id];
        draft.toItemId = opt.id;
        draft.toItemText = opt.label;
        draft.toPortId = false;
        draft.toPortText = "";
        const toItem = this.state.items.find((it) => it.id === opt.id);
        draft.toPortOptions = (toItem?.ports || [])
            .filter((p) => effectiveStatus(p, this.props.reservedPortIds) === "open")
            .map((p) => ({ id: p.id, label: p.label }));
    }

    onToPortInput(port, text) {
        this.state.connectDrafts[port.id].toPortText = text || "";
        this.state.connectDrafts[port.id].toPortId = false;
    }

    onToPortSelect(port, opt) {
        const draft = this.state.connectDrafts[port.id];
        draft.toPortId = opt.id;
        draft.toPortText = opt.label;
    }

    onHoseInput(port, text) {
        const draft = this.state.connectDrafts[port.id];
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
    async onHoseSelect(port, opt) {
        const draft = this.state.connectDrafts[port.id];
        draft.hoseId = opt.id;
        draft.hoseText = opt.label;
        draft.length = false;
        draft.lengthText = "";
        draft.lengthOptions = [];
        draft.lengthFilteredOptions = [];
        draft.lengthMatchId = false;
        draft.lengthMatchPartNumber = "";

        const options = await this.props.getLengthOptions(opt.id);
        // Race-guard: only apply if this draft still exists and is still on
        // the Hose that was picked when the call started.
        const current = this.state.connectDrafts[port.id];
        if (current && current.hoseId === opt.id) {
            current.lengthOptions = options;
            current.lengthFilteredOptions = options;
        }
    }

    onLengthInput(port, text) {
        const draft = this.state.connectDrafts[port.id];
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

    onLengthSelect(port, opt) {
        const draft = this.state.connectDrafts[port.id];
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
    onLengthBlur(port) {
        const draft = this.state.connectDrafts[port.id];
        if (!draft || draft.lengthMatchId || draft.length === false) {
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

    onAddClick(port) {
        const draft = this.state.connectDrafts[port.id];
        const toItem = this.state.items.find((it) => it.id === draft.toItemId);
        const toPort = toItem.ports.find((p) => p.id === draft.toPortId);
        const lengthMatch = draft.lengthMatchId
            ? { id: draft.lengthMatchId, part_number: draft.lengthMatchPartNumber, length: draft.length }
            : null;
        this.props.onAdd(
            this.selectedItem, port, toItem, toPort,
            { id: draft.hoseId, label: draft.hoseText }, draft.length, lengthMatch
        );
        this.state.connectDrafts[port.id] = emptyDraft();
    }

    onUsedClick(port) {
        this.props.onUsedPortClick(port.job_hose_line_id);
    }
}
