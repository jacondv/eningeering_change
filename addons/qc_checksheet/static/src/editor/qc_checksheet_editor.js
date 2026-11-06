/** @odoo-module **/

import { Component, markup, onWillStart, useExternalListener, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";
import { useSetupAction } from "@web/search/action_hook";
import { parseClipboardRows } from "./qc_clipboard";
import { compareSheets, rowsWithRemoved } from "./qc_compare";
import { QcNewSheet } from "./qc_new_sheet";
import { QcChangePicker } from "./qc_change_picker";
import { QcNewRevisionDialog } from "./qc_new_revision_dialog";
import { QcPreviewDialog } from "./qc_preview_dialog";
import { QcPromptDialog } from "./qc_prompt_dialog";
import { QcRichCell } from "./qc_rich_cell";

const CHECKSHEET_MODEL = "qc.checksheet";
const ITEM_COLUMNS = ["description", "acceptance", "note"];
const REPORT_NAME = "qc_checksheet.report_qc_checksheet_document";
const OUTLINE_MIN_WIDTH = 140;
const OUTLINE_MAX_WIDTH = 520;
const COLUMN_MIN_WIDTH = 120;
// Columns are shares of the table, so the table still fills a different screen.
// Same proportions as the report's Descriptions / Acceptance / Note columns.
const DEFAULT_LAYOUT = {
    outline: 220,
    columns: { description: 2.6, acceptance: 1.3, note: 1 },
};

function isPositiveNumber(value) {
    return Number.isFinite(value) && value > 0;
}

function layoutStorageKey() {
    return `qc_checksheet.editor.layout.${user.userId}`;
}

function loadLayout() {
    const layout = { ...DEFAULT_LAYOUT, columns: { ...DEFAULT_LAYOUT.columns } };
    try {
        const stored = JSON.parse(localStorage.getItem(layoutStorageKey())) || {};
        if (isPositiveNumber(stored.outline)) {
            layout.outline = Math.min(Math.max(stored.outline, OUTLINE_MIN_WIDTH), OUTLINE_MAX_WIDTH);
        }
        for (const field of ITEM_COLUMNS) {
            if (isPositiveNumber(stored.columns?.[field])) {
                layout.columns[field] = stored.columns[field];
            }
        }
    } catch {
        // Unreadable or blocked storage only costs the remembered layout.
    }
    return layout;
}

function htmlIsEmpty(html) {
    if (!html) {
        return true;
    }
    if (/<img/i.test(html)) {
        return false;
    }
    return !new DOMParser().parseFromString(html, "text/html").body.textContent.trim();
}

function htmlToText(html) {
    return new DOMParser().parseFromString(html || "", "text/html").body.textContent.trim();
}

/**
 * Client action of the Check Sheet Editor: the New Check Sheet page when its
 * context has no active_id, otherwise that sheet (active_id goes in the URL, so
 * a browser refresh comes back here). Changes stay in the browser until Save.
 * Moving between sheets or Revisions replaces this action.
 */
export class QcChecksheetEditor extends Component {
    static template = "qc_checksheet.Editor";
    static components = { QcNewSheet, QcRichCell, QcChangePicker };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.nextUid = 1;
        this.commitActive = null;
        this.dragged = null;
        this.state = useState({
            sheetId: this.props.action.context?.active_id || false,
            sheet: null,
            tab: "content",
            active: null,
            layout: loadLayout(),
            resizing: false,
            dirty: false,
            saving: false,
            dropTarget: null,
            // { baseId, base } while comparing with another Revision.
            compare: null,
        });

        useSetupAction({
            beforeLeave: () => this.confirmLeave(),
            beforeUnload: (ev) => {
                if (this.state.dirty) {
                    ev.preventDefault();
                    ev.returnValue = "";
                }
            },
        });
        useExternalListener(window, "keydown", (ev) => this.onWindowKeydown(ev));
        useExternalListener(window, "pointerdown", (ev) => this.onWindowPointerdown(ev));

        onWillStart(async () => {
            if (this.state.sheetId) {
                await this.load();
            }
        });
    }

    // Loading

    uid() {
        return `row_${this.nextUid++}`;
    }

    async load() {
        const sheet = await this.orm.call(CHECKSHEET_MODEL, "editor_load", [[this.state.sheetId]]);
        sheet.uid = this.uid();
        sheet.groups.forEach((group) => {
            group.uid = this.uid();
            group.items.forEach((item) => (item.uid = this.uid()));
        });
        sheet.positions.forEach((line) => (line.uid = this.uid()));
        this.state.sheet = sheet;
        this.state.dirty = false;
        this.state.active = null;
        this.commitActive = null;
        // What an Approver needs to see first is what changed: against the
        // previous Revision, or for a copied Rev 0 against what it was copied from.
        if (sheet.state === "review" && this.defaultBaseId) {
            await this.compareWith(this.defaultBaseId);
        } else if (this.state.compare) {
            await this.compareWith(this.state.compare.baseId);
        }
    }

    // Comparing Revisions

    get compareOptions() {
        const options = this.sheet.revisions
            .filter((rev) => rev.id !== this.sheet.id)
            .map((rev) => ({ id: rev.id, label: `Rev ${rev.revision} (${rev.state_label})` }));
        if (this.sheet.source) {
            options.push({ id: this.sheet.source.id, label: this.sheet.source.label });
        }
        return options;
    }

    get defaultBaseId() {
        return this.previousRevisionId || (this.sheet.revision === 0 && this.sheet.source?.id) || false;
    }

    get previousRevisionId() {
        const older = this.sheet.revisions.filter((rev) => rev.revision < this.sheet.revision);
        return older.at(-1)?.id || false;
    }

    async compareWith(baseId) {
        const base = await this.orm.call(CHECKSHEET_MODEL, "editor_load", [[baseId]]);
        this.state.compare = { baseId, base };
    }

    toggleCompare() {
        if (this.state.compare) {
            this.state.compare = null;
        } else {
            this.compareWith(this.defaultBaseId || this.compareOptions[0].id);
        }
    }

    onCompareBaseChange(ev) {
        this.compareWith(parseInt(ev.target.value));
    }

    get currentDiff() {
        return this.state.compare && compareSheets(this.state.compare.base, this.sheet);
    }

    get compareSummary() {
        const { counts, header } = this.currentDiff;
        const parts = [];
        for (const [count, label] of [
            [counts.added, "added"],
            [counts.changed, "changed"],
            [counts.removed, "removed"],
            [counts.moved, "moved"],
        ]) {
            if (count) {
                parts.push(`${count} ${label}`);
            }
        }
        if (header !== null) {
            parts.push("Header changed");
        }
        return parts.length ? parts.join(" · ") : "No differences";
    }

    /** The content rows, with removed ones put back in while comparing. */
    contentRows(entry, diff) {
        return diff ? rowsWithRemoved(entry.items, diff.removedItems.get(entry.group.uid)) : entry.items;
    }

    itemDiff(diff, item) {
        return diff?.items.get(item.uid);
    }

    cellDiffClass(itemDiff, field) {
        return itemDiff?.changed[field] !== undefined ? "o_qce_diff_changed" : "";
    }

    html(value) {
        return markup(value || "");
    }

    openSheet(id) {
        return this.action.doAction(
            {
                type: "ir.actions.client",
                tag: "qc_checksheet.editor",
                name: "Check Sheet",
                context: { active_id: id },
            },
            { stackPosition: "replaceCurrentAction" }
        );
    }

    openForm(id) {
        return this.action.doAction(
            {
                type: "ir.actions.act_window",
                res_model: CHECKSHEET_MODEL,
                res_id: id,
                views: [[false, "form"]],
            },
            { stackPosition: "replaceCurrentAction" }
        );
    }

    goToList() {
        return this.action.doAction("qc_checksheet.action_qc_checksheet_all", {
            clearBreadcrumbs: true,
        });
    }

    openJob() {
        return this.action.doAction({
            type: "ir.actions.client",
            tag: "qc_checksheet.job",
            name: `QC: ${this.sheet.job}`,
            context: { active_id: this.sheet.job_id },
        });
    }

    onCreated({ id, layout }) {
        return layout === "standard" ? this.openSheet(id) : this.openForm(id);
    }

    // Derived values

    get sheet() {
        return this.state.sheet;
    }

    get editable() {
        return !!this.sheet && this.sheet.state === "draft" && this.sheet.can_author;
    }

    get isCurrentRevisionView() {
        return this.sheet.id === this.sheet.latest_id;
    }

    get oldRevisionNotice() {
        if (this.sheet.state === "superseded") {
            return `You are viewing Rev ${this.sheet.revision}, which is superseded. It can be read and printed, but it must not be used.`;
        }
        if (!this.isCurrentRevisionView) {
            return `Rev ${this.sheet.revision} is still the Revision in use, while a newer Revision is being prepared.`;
        }
        return "";
    }

    get badgeClass() {
        return `o_qce_badge o_qce_badge_${this.sheet.state}`;
    }

    get saveLabel() {
        if (!this.editable) {
            return "Read only";
        }
        if (this.state.saving) {
            return "Saving...";
        }
        return this.state.dirty ? "Unsaved changes" : "All changes saved";
    }

    get saveLabelClass() {
        return this.state.dirty && this.editable ? "o_qce_unsaved" : "";
    }

    get numberedGroups() {
        let number = 0;
        return this.sheet.groups.map((group, index) => ({
            group,
            index: index + 1,
            title: htmlToText(group.name) || "Untitled Group",
            items: group.items.map((item) => ({ item, number: ++number })),
        }));
    }

    get totalItems() {
        return this.sheet.groups.reduce((total, group) => total + group.items.length, 0);
    }

    get layoutStyle() {
        const { outline, columns } = this.state.layout;
        return [
            `--qce-outline: ${outline}px`,
            ...ITEM_COLUMNS.map((field) => `--qce-col-${field}: ${columns[field]}fr`),
        ].join("; ");
    }

    isHistoryRowEditable(line) {
        return this.editable && line.rev === this.sheet.revision;
    }

    // Resizing

    saveLayout() {
        try {
            localStorage.setItem(layoutStorageKey(), JSON.stringify(this.state.layout));
        } catch {
            // The layout still applies until the page is closed.
        }
    }

    trackDrag(ev, onMove) {
        ev.preventDefault();
        const handle = ev.currentTarget;
        const startX = ev.clientX;
        handle.setPointerCapture(ev.pointerId);
        this.state.resizing = true;
        const move = (moveEv) => onMove(moveEv.clientX - startX);
        const stop = () => {
            handle.removeEventListener("pointermove", move);
            handle.removeEventListener("pointerup", stop);
            handle.removeEventListener("pointercancel", stop);
            this.state.resizing = false;
            this.saveLayout();
        };
        handle.addEventListener("pointermove", move);
        handle.addEventListener("pointerup", stop);
        handle.addEventListener("pointercancel", stop);
    }

    startOutlineDrag(ev) {
        const start = this.state.layout.outline;
        this.trackDrag(ev, (dx) => {
            this.state.layout.outline = Math.min(Math.max(start + dx, OUTLINE_MIN_WIDTH), OUTLINE_MAX_WIDTH);
        });
    }

    resetOutline() {
        this.state.layout.outline = DEFAULT_LAYOUT.outline;
        this.saveLayout();
    }

    /** Moves the line between two columns: one gets what the other gives up. */
    startColumnDrag(left, right, ev) {
        const leftCell = ev.currentTarget.parentElement;
        const leftStart = leftCell.getBoundingClientRect().width;
        const total = leftStart + leftCell.nextElementSibling.getBoundingClientRect().width;
        const { columns } = this.state.layout;
        const shares = columns[left] + columns[right];
        this.trackDrag(ev, (dx) => {
            const width = Math.min(Math.max(leftStart + dx, COLUMN_MIN_WIDTH), total - COLUMN_MIN_WIDTH);
            columns[left] = (shares * width) / total;
            columns[right] = shares - columns[left];
        });
    }

    resetColumns() {
        this.state.layout.columns = { ...DEFAULT_LAYOUT.columns };
        this.saveLayout();
    }

    // Keeping track of edits

    markDirty() {
        if (this.editable) {
            this.state.dirty = true;
        }
    }

    onNameInput(ev) {
        this.sheet.name = ev.target.value;
        this.markDirty();
    }

    setCell(record, field, html) {
        if (record[field] !== html) {
            record[field] = html;
            this.markDirty();
        }
    }

    cellKey(record, field) {
        return `${record.uid}:${field}`;
    }

    /** Every editable cell in reading order, for Tab and Shift+Tab. */
    get cellOrder() {
        const order = [];
        for (const group of this.sheet.groups) {
            order.push({ key: this.cellKey(group, "name"), group });
            for (const item of group.items) {
                for (const field of ITEM_COLUMNS) {
                    order.push({ key: this.cellKey(item, field), group, item, field });
                }
            }
        }
        return order;
    }

    async activate(key) {
        if (this.state.active === key) {
            return;
        }
        // Before this cell's editor goes away, in case it still holds an image upload.
        await this.commitActive?.();
        this.state.active = key;
    }

    registerCommit(commit) {
        this.commitActive = commit;
    }

    // Adding, removing, moving

    newItem(values = {}) {
        return { id: false, uid: this.uid(), description: "", acceptance: "", note: "", ...values };
    }

    addItem(group, afterItem = null) {
        const item = this.newItem();
        const at = afterItem ? group.items.indexOf(group.items.find((i) => i.uid === afterItem.uid)) + 1 : group.items.length;
        group.items.splice(at, 0, item);
        this.markDirty();
        this.activate(this.cellKey(item, "description"));
    }

    addItemAtEnd() {
        const lastGroup = this.sheet.groups.at(-1);
        if (lastGroup) {
            this.addItem(lastGroup);
        } else {
            this.addGroup();
        }
    }

    addGroup() {
        const group = { id: false, uid: this.uid(), name: "", items: [this.newItem()] };
        this.sheet.groups.push(group);
        this.state.tab = "content";
        this.markDirty();
        this.activate(this.cellKey(group, "name"));
    }

    confirm(title, body, label, onConfirm) {
        this.dialog.add(QcPromptDialog, {
            title,
            body,
            buttons: [
                { label, primary: true, onClick: onConfirm },
                { label: "Cancel", onClick: () => {} },
            ],
        });
    }

    removeItem(group, item) {
        const remove = () => {
            group.items.splice(group.items.findIndex((i) => i.uid === item.uid), 1);
            this.state.active = null;
            this.markDirty();
        };
        if (ITEM_COLUMNS.every((field) => htmlIsEmpty(item[field]))) {
            remove();
        } else {
            this.confirm("Delete this Item?", "Its content will be removed when you Save.", "Delete", remove);
        }
    }

    removeGroup(group) {
        const remove = () => {
            this.sheet.groups.splice(this.sheet.groups.findIndex((g) => g.uid === group.uid), 1);
            this.state.active = null;
            this.markDirty();
        };
        if (group.items.length) {
            this.confirm(
                "Delete this Group?",
                `It will be removed with its ${group.items.length} Item(s) when you Save.`,
                "Delete",
                remove
            );
        } else {
            remove();
        }
    }

    onDragStart(kind, uid, ev) {
        this.dragged = { kind, uid };
        ev.dataTransfer.effectAllowed = "move";
        ev.dataTransfer.setData("text/plain", uid);
        this.state.active = null;
    }

    onDragOver(uid, ev) {
        if (this.dragged) {
            ev.preventDefault();
            this.state.dropTarget = uid;
        }
    }

    onDragEnd() {
        this.dragged = null;
        this.state.dropTarget = null;
    }

    /** Dropped on a Group: a Group goes before it, an Item goes to its top. */
    onDropOnGroup(group, ev) {
        ev.preventDefault();
        const dragged = this.dragged;
        this.onDragEnd();
        if (!dragged) {
            return;
        }
        if (dragged.kind === "group") {
            const groups = this.sheet.groups;
            const from = groups.findIndex((g) => g.uid === dragged.uid);
            if (groups[from].uid !== group.uid) {
                const [moved] = groups.splice(from, 1);
                groups.splice(groups.findIndex((g) => g.uid === group.uid), 0, moved);
                this.markDirty();
            }
        } else {
            this.moveItem(dragged.uid, group, 0);
        }
    }

    /** Dropped on an Item: the dragged Item goes before it. */
    onDropOnItem(group, target, ev) {
        ev.preventDefault();
        ev.stopPropagation();
        const dragged = this.dragged;
        this.onDragEnd();
        if (dragged?.kind === "item" && dragged.uid !== target.uid) {
            this.moveItem(dragged.uid, group, target.uid);
        }
    }

    moveItem(uid, toGroup, before) {
        let moved = null;
        for (const group of this.sheet.groups) {
            const at = group.items.findIndex((item) => item.uid === uid);
            if (at >= 0) {
                [moved] = group.items.splice(at, 1);
                break;
            }
        }
        if (!moved) {
            return;
        }
        const at = before === 0 ? 0 : toGroup.items.findIndex((item) => item.uid === before);
        toGroup.items.splice(at < 0 ? toGroup.items.length : at, 0, moved);
        this.markDirty();
    }

    jumpToGroup(entry) {
        this.state.tab = "content";
        const el = document.getElementById(`qce_${entry.group.uid}`);
        el?.scrollIntoView({ behavior: "smooth", block: "center" });
    }

    addPosition() {
        this.sheet.positions.push({ id: false, uid: this.uid(), position: "" });
        this.markDirty();
    }

    removePosition(index) {
        this.sheet.positions.splice(index, 1);
        this.markDirty();
    }

    onPositionInput(line, ev) {
        line.position = ev.target.value;
        this.markDirty();
    }

    onHistoryInput(line, field, ev) {
        line[field] = field === "show_in_report" ? ev.target.checked : ev.target.value;
        this.markDirty();
    }

    // Keyboard and paste

    onCellKeydown(entry, ev) {
        if (ev.ctrlKey && ev.key === "Enter") {
            ev.preventDefault();
            ev.stopPropagation();
            if (entry.item) {
                this.addItem(entry.group, entry.item);
            } else {
                this.state.active = entry.group.items.length
                    ? this.cellKey(entry.group.items[0], "description")
                    : this.addItem(entry.group);
            }
            return;
        }
        if (ev.key !== "Tab") {
            return;
        }
        // Capture phase: this takes Tab away from the editor's own indent.
        ev.preventDefault();
        ev.stopPropagation();
        const order = this.cellOrder;
        const here = order.findIndex((cell) => cell.key === this.state.active);
        const isLastOfGroup =
            entry.field === "note" && entry.group.items.at(-1)?.uid === entry.item?.uid;
        if (!ev.shiftKey && isLastOfGroup && !ITEM_COLUMNS.every((f) => htmlIsEmpty(entry.item[f]))) {
            this.addItem(entry.group, entry.item);
            return;
        }
        const next = order[here + (ev.shiftKey ? -1 : 1)];
        if (next) {
            this.activate(next.key);
        }
    }

    /** A table copied from Word or Excel fills rows, starting at this cell's column. */
    onCellPaste(entry, ev) {
        if (!entry.item) {
            return;
        }
        const rows = parseClipboardRows(ev.clipboardData);
        if (!rows) {
            return;
        }
        ev.preventDefault();
        ev.stopPropagation();
        const startColumn = ITEM_COLUMNS.indexOf(entry.field);
        const filled = rows.map((cells) => {
            const values = {};
            ITEM_COLUMNS.slice(startColumn).forEach((field, i) => (values[field] = cells[i] || ""));
            return values;
        });
        const { group, item } = entry;
        let at = group.items.findIndex((i) => i.uid === item.uid);
        if (ITEM_COLUMNS.every((field) => htmlIsEmpty(item[field]))) {
            Object.assign(item, filled.shift());
        }
        for (const values of filled) {
            group.items.splice(++at, 0, this.newItem(values));
        }
        this.state.active = null;
        this.markDirty();
        this.notification.add(`${rows.length} row(s) pasted`, { type: "success" });
    }

    onWindowKeydown(ev) {
        if (ev.ctrlKey && !ev.shiftKey && ev.key.toLowerCase() === "s" && this.sheet) {
            ev.preventDefault();
            if (this.editable) {
                this.save();
            }
        }
    }

    /** A click outside the table closes the active cell; the toolbar is not outside. */
    onWindowPointerdown(ev) {
        if (!this.state.active || !(ev.target instanceof Element)) {
            return;
        }
        if (!ev.target.closest(".o_qce_cell, .o_qce_rich_cell, .o-we-toolbar, .o-overlay-container, .modal")) {
            this.activate(null);
        }
    }

    // Saving and the workflow

    async save() {
        if (!this.editable || this.state.saving) {
            return false;
        }
        await this.commitActive?.();
        const { sheet } = this;
        this.state.saving = true;
        try {
            const saved = await this.orm.call(CHECKSHEET_MODEL, "editor_save", [
                [sheet.id],
                {
                    version: sheet.version,
                    name: sheet.name,
                    groups: sheet.groups.map((group) => ({
                        id: group.id,
                        name: group.name,
                        items: group.items.map((item) => ({
                            id: item.id,
                            description: item.description,
                            acceptance: item.acceptance,
                            note: item.note,
                        })),
                    })),
                    positions: sheet.positions.map((line) => ({ id: line.id, position: line.position })),
                    history: sheet.history.map((line) => ({
                        id: line.id,
                        description: line.description,
                        date: line.date,
                        show_in_report: line.show_in_report,
                    })),
                },
            ]);
            // Only new rows' ids and the version: the open cell keeps its caret.
            sheet.version = saved.version;
            saved.groups.forEach((savedGroup, groupIndex) => {
                const group = sheet.groups[groupIndex];
                group.id = savedGroup.id;
                savedGroup.item_ids.forEach((id, itemIndex) => (group.items[itemIndex].id = id));
            });
            saved.positions.forEach((id, index) => (sheet.positions[index].id = id));
            this.state.dirty = false;
            return true;
        } finally {
            this.state.saving = false;
        }
    }

    /** Workflow steps always act on what's on screen, so unsaved work is saved first. */
    async saveThen(step) {
        if (this.state.dirty && !(await this.save())) {
            if (this.state.saving) {
                this.notification.add("Still saving, try again in a moment.", { type: "warning" });
            }
            return;
        }
        await step();
    }

    submit() {
        return this.saveThen(async () => {
            await this.orm.call(CHECKSHEET_MODEL, "action_submit", [[this.sheet.id]]);
            await this.load();
        });
    }

    async recall() {
        await this.orm.call(CHECKSHEET_MODEL, "action_recall", [[this.sheet.id]]);
        await this.load();
    }

    async approve() {
        await this.orm.call(CHECKSHEET_MODEL, "action_approve", [[this.sheet.id]]);
        await this.load();
    }

    askReason(title, inputLabel, confirmLabel, onConfirm) {
        this.dialog.add(QcPromptDialog, {
            title,
            inputLabel,
            buttons: [
                { label: confirmLabel, primary: true, onClick: onConfirm },
                { label: "Cancel", needsInput: false, onClick: () => {} },
            ],
        });
    }

    reject() {
        this.askReason("Reject this Check Sheet", "What needs to be corrected", "Reject", async (reason) => {
            await this.orm.call(CHECKSHEET_MODEL, "action_reject", [[this.sheet.id], reason]);
            await this.load();
        });
    }

    newRevision() {
        this.dialog.add(QcNewRevisionDialog, {
            search: (term) => this.searchChanges(term),
            onConfirm: async (reason, changes) => {
                const action = await this.orm.call(CHECKSHEET_MODEL, "action_create_revision", [
                    [this.sheet.id],
                    reason,
                    changes.map((change) => change.id),
                ]);
                await this.openSheet(action.res_id);
            },
        });
    }

    // Engineering Changes of this Revision

    searchChanges(term) {
        return this.orm.call(CHECKSHEET_MODEL, "editor_search_changes", [[this.sheet.id], term]);
    }

    /** Saved at once, apart from the sheet's own Save. */
    async setChanges(changes) {
        this.sheet.changes = await this.orm.call(CHECKSHEET_MODEL, "editor_set_changes", [
            [this.sheet.id],
            changes.map((change) => change.id),
        ]);
    }

    openChange(change) {
        return this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "engineering.change",
            res_id: change.id,
            views: [[false, "form"]],
        });
    }

    discardDraft() {
        const { sheet } = this;
        this.confirm(
            "Discard this Draft?",
            sheet.revision ? `Rev ${sheet.revision} and its changes will be lost.` : "This check sheet will be deleted.",
            "Discard",
            async () => {
                const previous = sheet.history.find((line) => line.rev === sheet.revision - 1)?.sheet_id;
                this.state.dirty = false;
                await this.orm.unlink(CHECKSHEET_MODEL, [sheet.id]);
                await (previous ? this.openSheet(previous) : this.goToList());
            }
        );
    }

    /** The real PDF, so it shows everything the report prints; unsaved work is saved first. */
    openPreview() {
        return this.saveThen(() =>
            this.dialog.add(QcPreviewDialog, {
                title: `Preview: ${this.sheet.number} · Rev ${this.sheet.revision}`,
                url: `/report/pdf/${REPORT_NAME}/${this.sheet.id}`,
                onPrint: () => this.printPdf(),
            })
        );
    }

    printPdf() {
        return this.saveThen(() =>
            this.action.doAction("qc_checksheet.action_report_qc_checksheet", {
                additionalContext: { active_ids: [this.sheet.id], active_model: CHECKSHEET_MODEL },
            })
        );
    }

    viewRevision(line) {
        return this.openSheet(line.sheet_id);
    }

    confirmLeave() {
        if (!this.state.dirty) {
            return true;
        }
        return new Promise((resolve) => {
            this.dialog.add(QcPromptDialog, {
                title: "Save your changes?",
                body: "This check sheet has changes that are not saved yet.",
                onDismiss: () => resolve(false),
                buttons: [
                    { label: "Save", primary: true, onClick: async () => resolve(await this.save()) },
                    {
                        label: "Discard changes",
                        onClick: () => {
                            this.state.dirty = false;
                            resolve(true);
                        },
                    },
                    { label: "Stay here", onClick: () => resolve(false) },
                ],
            });
        });
    }
}

registry.category("actions").add("qc_checksheet.editor", QcChecksheetEditor);
