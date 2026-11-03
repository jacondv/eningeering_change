/** @odoo-module **/

import { Component, useEffect, useExternalListener, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { formatClipboardRows } from "./pnm_clipboard";

const COLUMN_WIDTHS_STORAGE_KEY = "part_number_manager.part_management_page.recent_column_widths";
const MIN_COLUMN_WIDTH = 60;
const LEGACY_COLUMN_KEY = "legacy";
// No. and Time are the same order, so `sortable` columns share one switch,
// without having to parse Time's locale-formatted string.
const COLUMNS = [
    { key: "sequence", label: "No.", field: "sequence", width: 60, sortable: true },
    { key: LEGACY_COLUMN_KEY, label: "Old Part Number", field: "legacy_label", width: 160, selectable: true, copyable: true },
    { key: "material_group", label: "Material Group", field: "material_group_label", width: 130, selectable: true, copyable: true },
    { key: "part_number", label: "Part Number", field: "part_number", width: 120, selectable: true, copyable: true },
    { key: "job_number", label: "Job Number", field: "job_number_label", width: 120, selectable: true, copyable: true },
    { key: "short_description", label: "Short Description", field: "short_description", width: 180, selectable: true, copyable: true },
    { key: "long_description", label: "Long Description", field: "long_description", width: 220, selectable: true, copyable: true },
    { key: "part_type", label: "Part Type", field: "part_type_label", width: 130, selectable: true, copyable: true },
    { key: "vendor", label: "Vendor", field: "vendor_label", width: 150, selectable: true, copyable: true },
    { key: "vendor_ref", label: "Vendor Part No.", field: "vendor_ref", width: 150, selectable: true, copyable: true },
    { key: "make_buy", label: "Make/Buy", field: "make_buy", width: 110, selectable: true, copyable: true },
    { key: "time", label: "Time", field: "time", width: 100, selectable: true, sortable: true },
];

// A running log of what was just created/converted, so a user who saved a batch
// can get back to any of it: click a cell to copy it, drag over cells and press
// Ctrl+C to copy a block as in Excel, or copy a whole column from its header.
export class PnmRecentPartsTable extends Component {
    static template = "part_number_manager.PnmRecentPartsTable";
    static props = {
        parts: Array, // newest first, see PartManagementPage
        onOpenPart: Function, // (partId) => void
        onClear: Function, // () => void
    };

    setup() {
        this.notification = useService("notification");
        this.parts = useState(this.props.parts);
        this.state = useState({
            columnWidths: this._loadColumnWidths(),
            newestFirst: false,
            // {anchor: {row, column}, focus: {row, column}}, as displayed.
            selection: null,
        });
        this.isDragging = false;

        useExternalListener(window, "mousedown", this.onWindowMouseDown);
        useExternalListener(window, "mouseup", this.onWindowMouseUp);
        useExternalListener(document, "copy", this.onCopy);
        // Rows and columns have moved: the same positions now mean other cells.
        useEffect(
            () => this._clearSelection(),
            () => [this.state.newestFirst, this.parts.length]
        );
    }

    get columns() {
        const hasLegacy = this.parts.some((part) => part.legacy_label);
        return COLUMNS.filter((column) => column.key !== LEGACY_COLUMN_KEY || hasLegacy);
    }

    // Each part's number, 1 being the first one created, whichever way it's displayed.
    get rows() {
        const rows = this.parts.map((part, index) => ({ ...part, sequence: this.parts.length - index }));
        return this.state.newestFirst ? rows : rows.reverse();
    }

    get sortDirection() {
        return this.state.newestFirst ? "descending" : "ascending";
    }

    toggleOrder() {
        this.state.newestFirst = !this.state.newestFirst;
    }

    get selectionBounds() {
        const { selection } = this.state;
        return selection && {
            top: Math.min(selection.anchor.row, selection.focus.row),
            bottom: Math.max(selection.anchor.row, selection.focus.row),
            left: Math.min(selection.anchor.column, selection.focus.column),
            right: Math.max(selection.anchor.column, selection.focus.column),
        };
    }

    isCellSelected(row, column) {
        const bounds = this.selectionBounds;
        return !!bounds
            && row >= bounds.top && row <= bounds.bottom
            && column >= bounds.left && column <= bounds.right;
    }

    onCellMouseDown(row, column, ev) {
        if (ev.button === 0 && this.columns[column].selectable) {
            this.isDragging = true;
            this.state.selection = { anchor: { row, column }, focus: { row, column } };
        }
    }

    onCellMouseEnter(row, column) {
        if (this.isDragging && this.columns[column].selectable) {
            this.state.selection.focus = { row, column };
        }
    }

    onWindowMouseDown(ev) {
        if (!ev.target.closest(".o_pnm_recent_cell")) {
            this._clearSelection();
        }
    }

    _clearSelection() {
        this.isDragging = false;
        this.state.selection = null;
    }

    onWindowMouseUp() {
        if (!this.isDragging) {
            return;
        }
        this.isDragging = false;
        const { top, bottom, left, right } = this.selectionBounds;
        if (top === bottom && left === right) {
            this._copyText(this._cellText(this.rows[top], this.columns[left]));
        }
    }

    onCopy(ev) {
        const bounds = this.selectionBounds;
        if (!bounds || ev.target.closest?.("input, textarea")) {
            return;
        }
        const columns = this.columns.slice(bounds.left, bounds.right + 1);
        const rows = this.rows.slice(bounds.top, bounds.bottom + 1);
        ev.preventDefault();
        ev.clipboardData.setData("text/plain", formatClipboardRows(
            rows.map((row) => columns.map((column) => this._cellText(row, column)))
        ));
        this.notification.add("Copied to clipboard.", { type: "success" });
    }

    onCopyColumn(column) {
        const cells = this.rows.map((row) => [this._cellText(row, column)]);
        if (cells.some(([text]) => text)) {
            this._copyText(formatClipboardRows(cells));
        }
    }

    _cellText(row, column) {
        return String(row[column.field] || "");
    }

    async _copyText(text) {
        if (!text) {
            return;
        }
        try {
            await navigator.clipboard.writeText(text);
            this.notification.add("Copied to clipboard.", { type: "success" });
        } catch {
            this.notification.add("Could not copy to clipboard.", { type: "danger" });
        }
    }

    _loadColumnWidths() {
        const defaults = Object.fromEntries(COLUMNS.map((column) => [column.key, column.width]));
        try {
            return { ...defaults, ...JSON.parse(localStorage.getItem(COLUMN_WIDTHS_STORAGE_KEY) || "{}") };
        } catch {
            return defaults;
        }
    }

    _saveColumnWidths() {
        try {
            localStorage.setItem(COLUMN_WIDTHS_STORAGE_KEY, JSON.stringify(this.state.columnWidths));
        } catch {
            // Not remembered this time - not fatal, columns just default back next visit.
        }
    }

    onColumnResizeStart(columnKey, ev) {
        ev.preventDefault();
        const startX = ev.clientX;
        const startWidth = this.state.columnWidths[columnKey];
        const onMouseMove = (moveEv) => {
            this.state.columnWidths[columnKey] = Math.max(MIN_COLUMN_WIDTH, startWidth + (moveEv.clientX - startX));
        };
        const onMouseUp = () => {
            window.removeEventListener("mousemove", onMouseMove);
            window.removeEventListener("mouseup", onMouseUp);
            this._saveColumnWidths();
        };
        window.addEventListener("mousemove", onMouseMove);
        window.addEventListener("mouseup", onMouseUp);
    }
}
