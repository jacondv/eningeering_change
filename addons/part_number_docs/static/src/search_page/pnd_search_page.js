/** @odoo-module **/

import { Component, markup, onMounted, onWillStart, onWillUnmount, useEffect, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { _t } from "@web/core/l10n/translation";
import { copyPathToOpen } from "../open_path/pnd_open_path";
import { dragFrom, useLayoutPrefs } from "./pnd_layout";

const MODEL = "pnd.document";
const SEARCH_DELAY = 300; // ms
const PARTS_SHOWN = 5; // part numbers listed before "Show more"
const SCOPES = [
    { key: "all", label: _t("All") },
    { key: "part_number", label: _t("Part Number") },
    { key: "part_description", label: _t("Part Description") },
    { key: "vendor", label: _t("Vendor") },
    { key: "vendor_ref", label: _t("Vendor Part No.") },
    { key: "title", label: _t("Title") },
    { key: "type", label: _t("Type") },
    { key: "description", label: _t("Notes & Description") },
];
// The columns of the list; the title cannot be hidden.
const COLUMNS = [
    { key: "title", label: _t("Title"), width: 260, required: true },
    { key: "type", label: _t("Type"), width: 110 },
    { key: "parts", label: _t("Part Numbers"), width: 230 },
    { key: "vendor", label: _t("Vendor"), width: 140 },
    { key: "source", label: _t("Source"), width: 120 },
    { key: "updated", label: _t("Updated"), width: 100 },
];
const MIN_COLUMN = 60;
const CHECK_WIDTH = 28;
const ICON_WIDTH = 32;
const IMAGE_EXTENSIONS = ["png", "jpg", "jpeg", "gif", "webp"];

/**
 * Part Documents: one search box over every document of every part number, a list of what is
 * found, and the document itself beside it. What a user may do (add, change, merge, delete) is
 * decided on the server by their access level; the buttons only follow it.
 */
export class PndSearchPage extends Component {
    static template = "part_number_docs.SearchPage";
    static components = { Dropdown, DropdownItem };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.scopes = SCOPES;
        this.columns = COLUMNS;
        this.layout = useLayoutPrefs("part_documents_search", { splitPct: 58 });
        this.rootRef = useRef("root");
        this.selectAllRef = useRef("selectAll");
        this.state = useState({
            options: { types: [], kinds: [], can_edit: false, can_manage: false, windows_folder: "", root_name: "" },
            query: "",
            facets: [], // the chips of the search box: { scope, value }
            focused: false,
            suggestIndex: 0,
            dragging: false,
            typeIds: [],
            kinds: [],
            archived: false,
            rows: [],
            total: 0,
            loading: true,
            selectedId: false,
            preview: null,
            checked: [],
            expanded: false,
            allParts: false,
            folderDraft: "",
        });
        this.requestId = 0;
        this.previewRequestId = 0;
        this.timer = null;
        onWillStart(async () => {
            this.state.options = await this.orm.call(MODEL, "get_page_options", []);
            this.state.folderDraft = this.state.options.windows_folder;
            await this.search();
        });
        onMounted(() => this.focusSearch());
        onWillUnmount(() => clearTimeout(this.timer));
        // The "select all" box shows a dash when only some rows are ticked.
        useEffect(
            () => {
                const box = this.selectAllRef.el;
                if (box) {
                    box.indeterminate = this.state.checked.length > 0 && !this.allChecked;
                }
            },
            () => [this.state.checked.length, this.state.rows.length]
        );
    }

    focusSearch() {
        document.querySelector(".o_pnd_search input.o_pnd_query")?.focus();
    }

    // -- searching -----------------------------------------------------
    onQueryInput(ev) {
        this.state.query = ev.target.value;
        this.state.suggestIndex = 0;
        clearTimeout(this.timer);
        this.timer = setTimeout(() => this.search(), SEARCH_DELAY);
    }

    onFilterChange() {
        this.search();
    }

    // -- the search box: free text, and chips ("Vendor: klixon") -------------
    scopeLabel(key) {
        return SCOPES.find((scope) => scope.key === key)?.label || key;
    }

    onQueryFocus() {
        this.state.focused = true;
    }

    onQueryBlur() {
        this.state.focused = false;
    }

    /** Turns what is typed into a chip of the chosen kind ("Search Vendor for: ..."). */
    addFacet(scope) {
        const value = this.state.query.trim();
        if (!value) {
            return;
        }
        clearTimeout(this.timer);
        this.state.facets.push({ scope, value });
        this.state.query = "";
        this.state.suggestIndex = 0;
        this.search();
    }

    removeFacet(index) {
        this.state.facets.splice(index, 1);
        this.search();
    }

    onQueryKeydown(ev) {
        const count = this.scopes.length;
        if (ev.key === "Enter") {
            this.addFacet(this.scopes[this.state.suggestIndex].key);
        } else if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
            ev.preventDefault();
            const step = ev.key === "ArrowDown" ? 1 : -1;
            this.state.suggestIndex = (this.state.suggestIndex + step + count) % count;
        } else if (ev.key === "Backspace" && !this.state.query && this.state.facets.length) {
            this.removeFacet(this.state.facets.length - 1);
        } else if (ev.key === "Escape") {
            ev.target.blur();
        }
    }

    toggleIn(list, value) {
        const index = list.indexOf(value);
        if (index === -1) {
            list.push(value);
        } else {
            list.splice(index, 1);
        }
        this.search();
    }

    clearFilter(list) {
        list.splice(0, list.length);
        this.search();
    }

    /** What a filter button says: "Type", "Type: Datasheet" or "Type: 3" (three chosen). */
    filterLabel(title, chosen, all, key) {
        if (!chosen.length) {
            return title;
        }
        if (chosen.length > 1) {
            return `${title}: ${chosen.length}`;
        }
        const item = all.find((entry) => entry[key] === chosen[0]);
        return `${title}: ${item ? item.name ?? item.label : ""}`;
    }

    get typeLabel() {
        return this.filterLabel(_t("Type"), this.state.typeIds, this.state.options.types, "id");
    }

    get sourceLabel() {
        return this.filterLabel(_t("Source"), this.state.kinds, this.state.options.kinds, "key");
    }

    async search(append = false) {
        const request = ++this.requestId;
        this.state.loading = true;
        let result;
        try {
            result = await this.orm.call(MODEL, "search_documents", [], {
                query: this.state.query,
                scope: "all",
                facets: this.state.facets.map((facet) => ({ ...facet })),
                filters: {
                    type_ids: [...this.state.typeIds],
                    kinds: [...this.state.kinds],
                    archived: this.state.archived,
                },
                offset: append ? this.state.rows.length : 0,
            });
        } catch (error) {
            if (request === this.requestId) {
                this.state.loading = false; // not stuck on "Searching..."
            }
            throw error;
        }
        if (request !== this.requestId) {
            return; // a newer search is on its way
        }
        this.state.rows = append ? [...this.state.rows, ...result.rows] : result.rows;
        if (result.total !== null) {
            this.state.total = result.total; // only the first page counts
        }
        this.state.loading = false;
        if (!append) {
            this.state.checked = this.state.checked.filter((id) => result.rows.some((row) => row.id === id));
            if (!result.rows.some((row) => row.id === this.state.selectedId)) {
                this.state.selectedId = false;
                this.state.preview = null;
            }
        }
    }

    get hasMore() {
        return this.state.rows.length < this.state.total;
    }

    // -- one document --------------------------------------------------
    async select(row) {
        this.state.selectedId = row.id;
        this.state.expanded = false;
        this.state.allParts = false;
        await this.loadPreview(row.id);
    }

    /** Shows a document in the right pane; the answer of a click that is no longer the last is dropped. */
    async loadPreview(id) {
        const request = ++this.previewRequestId;
        const preview = await this.orm.call(MODEL, "get_preview", [[id]]);
        if (request === this.previewRequestId && this.state.selectedId === id) {
            this.state.preview = preview;
        }
    }

    // -- ticking rows --------------------------------------------------
    get allChecked() {
        return this.state.rows.length > 0 && this.state.rows.every((row) => this.state.checked.includes(row.id));
    }

    toggleAll() {
        this.state.checked = this.allChecked ? [] : this.state.rows.map((row) => row.id);
    }

    toggleChecked(row, ev) {
        ev.stopPropagation();
        const index = this.state.checked.indexOf(row.id);
        if (index === -1) {
            this.state.checked.push(row.id);
        } else {
            this.state.checked.splice(index, 1);
        }
    }

    get checkedRows() {
        return this.state.rows.filter((row) => this.state.checked.includes(row.id));
    }

    get canArchive() {
        return this.checkedRows.some((row) => row.active);
    }

    get canRestore() {
        return this.checkedRows.some((row) => !row.active);
    }

    // -- what a row looks like -----------------------------------------
    iconFor(row) {
        if (row.kind === "link") {
            return "fa-link text-primary";
        }
        if (row.kind === "path") {
            return "fa-cloud text-info"; // a file of the shared SharePoint/OneDrive library
        }
        if (row.kind === "note") {
            return "fa-sticky-note-o text-success";
        }
        if (row.extension === "pdf") {
            return "fa-file-pdf-o text-danger";
        }
        return IMAGE_EXTENSIONS.includes(row.extension) ? "fa-file-image-o text-info" : "fa-file-o";
    }

    kindLabel(row) {
        if (row.kind === "file") {
            return row.extension ? row.extension.toUpperCase() : _t("File");
        }
        return { link: _t("Link"), path: _t("Path"), note: _t("Note") }[row.kind];
    }

    /** The note as the page shows it (the server keeps only safe HTML in it). */
    get noteHtml() {
        return markup(this.state.preview?.note || "");
    }

    get visibleParts() {
        const parts = this.state.preview?.part_numbers || [];
        return this.state.allParts ? parts : parts.slice(0, PARTS_SHOWN);
    }

    get hiddenPartCount() {
        // Of all its part numbers (the panel is sent the first ones only).
        return Math.max((this.state.preview?.part_count || 0) - PARTS_SHOWN, 0);
    }

    get previewKind() {
        const preview = this.state.preview;
        if (!preview || preview.kind !== "file") {
            return preview?.kind;
        }
        return preview.mimetype === "application/pdf" ? "pdf" : "image";
    }

    fileUrl(preview, download = false) {
        const base = `/web/content/${MODEL}/${preview.id}/file/${encodeURIComponent(preview.file_name || "file")}`;
        return download ? `${base}?download=true` : base;
    }

    // -- actions -------------------------------------------------------
    download(preview) {
        window.open(this.fileUrl(preview, true));
    }

    openForm(resId) {
        return this.action.doAction(
            {
                type: "ir.actions.act_window",
                res_model: MODEL,
                res_id: resId || false,
                views: [[false, "form"]],
                target: "new",
                context: resId ? {} : { default_type_id: this.state.options.default_type_id },
            },
            { onClose: () => this.refresh() }
        );
    }

    async refresh() {
        const selected = this.state.selectedId;
        await this.search();
        if (selected && this.state.rows.some((row) => row.id === selected)) {
            this.state.selectedId = selected;
            await this.loadPreview(selected);
        }
    }

    async archiveChecked() {
        const ids = this.checkedRows.filter((row) => row.active).map((row) => row.id);
        await this.orm.call(MODEL, "action_archive", [ids]);
        this.state.checked = [];
        await this.refresh();
    }

    async restoreChecked() {
        const ids = this.checkedRows.filter((row) => !row.active).map((row) => row.id);
        await this.orm.call(MODEL, "action_unarchive", [ids]);
        this.state.checked = [];
        await this.refresh();
    }

    deleteChecked() {
        const ids = [...this.state.checked];
        this.dialog.add(ConfirmationDialog, {
            title: _t("Delete documents"),
            body: _t("Delete %s document(s) for good? This cannot be undone. (Archiving only hides them.)", ids.length),
            confirmLabel: _t("Delete"),
            confirm: async () => {
                await this.orm.unlink(MODEL, ids);
                this.state.checked = [];
                this.state.selectedId = false;
                this.state.preview = null;
                await this.search();
            },
            cancel: () => {},
        });
    }

    async mergeChecked() {
        const action = await this.orm.call(MODEL, "action_open_merge", [this.state.checked]);
        await this.action.doAction(action, {
            onClose: async () => {
                this.state.checked = [];
                await this.refresh();
            },
        });
    }

    // -- the layout the user arranged (remembered) -------------------------------
    get visibleColumns() {
        return COLUMNS.filter((column) => column.required || !this.layout.state.hidden.includes(column.key));
    }

    columnWidth(column) {
        return this.layout.state.widths[column.key] || column.width;
    }

    get tableWidth() {
        const fixed = ICON_WIDTH + (this.state.options.can_edit ? CHECK_WIDTH : 0);
        return fixed + this.visibleColumns.reduce((sum, column) => sum + this.columnWidth(column), 0);
    }

    toggleColumn(column) {
        const hidden = this.layout.state.hidden;
        const index = hidden.indexOf(column.key);
        if (index === -1) {
            hidden.push(column.key);
        } else {
            hidden.splice(index, 1);
        }
        this.layout.save();
    }

    resetLayout() {
        this.layout.reset();
    }

    /** Drag the right edge of a header to change the column's width. */
    onColumnResize(ev, column) {
        ev.stopPropagation();
        const start = this.columnWidth(column);
        this.state.dragging = true;
        dragFrom(
            ev,
            (dx) => {
                this.layout.state.widths[column.key] = Math.max(MIN_COLUMN, Math.round(start + dx));
            },
            () => {
                this.state.dragging = false;
                this.layout.save();
            }
        );
    }

    resetColumnWidth(column) {
        delete this.layout.state.widths[column.key];
        this.layout.save();
    }

    /** Drag the bar between the list and the document to share the width differently. */
    onSplitStart(ev) {
        const box = this.rootRef.el.getBoundingClientRect();
        const start = this.layout.state.splitPct;
        this.state.dragging = true;
        dragFrom(
            ev,
            (dx) => {
                const pct = start + (dx / box.width) * 100;
                this.layout.state.splitPct =
                    Math.round(Math.min(Math.max(pct, this.layout.MIN_SPLIT), this.layout.MAX_SPLIT) * 10) / 10;
            },
            () => {
                this.state.dragging = false;
                this.layout.save();
            }
        );
    }

    resetSplit() {
        this.layout.state.splitPct = 58;
        this.layout.save();
    }

    openPart(part) {
        return this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "part_number_manager.part_number",
            res_id: part.id,
            views: [[false, "form"]],
        });
    }

    async saveFolder() {
        const folder = await this.orm.call(MODEL, "set_my_windows_folder", [this.state.folderDraft]);
        this.state.options.windows_folder = folder;
        this.state.folderDraft = folder;
        this.notification.add(folder ? _t("Saved.") : _t("Removed."), { type: "success" });
        if (this.state.selectedId) {
            await this.loadPreview(this.state.selectedId);
        }
    }

    onFolderKeydown(ev) {
        if (ev.key === "Enter") {
            this.saveFolder();
        }
    }

    openPath(preview) {
        return copyPathToOpen(this.notification, preview.copy_text);
    }
}

registry.category("actions").add("part_number_docs.search_page", PndSearchPage);
