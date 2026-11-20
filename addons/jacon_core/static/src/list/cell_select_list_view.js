import { patch } from "@web/core/utils/patch";
import { onMounted, onWillUnmount, useEffect } from "@odoo/owl";
import { ListRenderer } from "@web/views/list/list_renderer";
import { _t } from "@web/core/l10n/translation";

/**
 * Excel-like cell selection for list views, opt-in per list.
 *
 * Add `class="o_jacon_cell_select"` to the <list> tag of a view to get it:
 *   - press on a cell and drag: the rectangle of cells under the mouse is selected (not whole rows);
 *   - Shift+click a cell: extends the selection from where it started;
 *   - Ctrl+C: copies the selected cells with the titles of their columns on the first line, as a table
 *     (HTML, for a mail or Word) and as text with tabs (for Excel);
 *   - Esc, or a click elsewhere: clears the selection.
 * A plain click (no drag) works as before and opens the record.
 *
 * Patched on the core ListRenderer like resizable_column_list_view.js, so any list of any module
 * can use it by adding the class; lists without it are not touched.
 */
const OPT_IN_CLASS = "o_jacon_cell_select";
const DRAG_THRESHOLD = 4; // px the mouse must move before a press counts as a drag
const CELL_SELECTOR = "td.o_data_cell";
const IGNORED_TARGETS = "input, textarea, select, button";
const SELECTED = "o_jacon_cell_selected";
const EDGES = { top: "o_jacon_cs_top", bottom: "o_jacon_cs_bottom", left: "o_jacon_cs_left", right: "o_jacon_cs_right" };

patch(ListRenderer.prototype, {
    setup() {
        super.setup();
        this.jaconSel = {
            anchor: null, // {row, col}: where the selection started
            focus: null, // {row, col}: where it ends now
            signature: "", // the records shown when it was made
            dragging: false,
            swallowClick: false,
            grid: null, // the cells of the table, read once per render: { rows: [[td]], index: Map(td -> {row, col}) }
            painted: [], // the cells that carry the selection classes now
        };
        this.jaconSelCleanups = [];
        onMounted(() => this.jaconCellSelectInit());
        onWillUnmount(() => this.jaconSelCleanups.forEach((cleanup) => cleanup()));
        // A render may replace the cells: read them again next time and paint the selection on the new ones.
        // Nothing is touched when there is no selection, so unrelated renders cost nothing.
        useEffect(() => {
            this.jaconSel.grid = null;
            this.jaconSel.painted = [];
            if (this.jaconSel.anchor) {
                if (this.jaconSel.signature === this.jaconSignature()) {
                    this.jaconPaintSelection();
                } else {
                    this.jaconSel.anchor = this.jaconSel.focus = null; // other records: the old range means nothing
                }
            }
        });
    },

    get jaconCellSelectEnabled() {
        return (this.props.archInfo?.className || "").split(/\s+/).includes(OPT_IN_CLASS);
    },

    jaconCellSelectInit() {
        // The listeners sit on the renderer's root, which lives as long as the list (the table inside it
        // can come and go: no records, then records).
        const root = this.rootRef?.el;
        if (!root || !this.jaconCellSelectEnabled) {
            return;
        }
        const listen = (target, type, handler, capture = false) => {
            target.addEventListener(type, handler, capture);
            this.jaconSelCleanups.push(() => target.removeEventListener(type, handler, capture));
        };
        listen(root, "pointerdown", (ev) => this.jaconOnPointerDown(ev));
        // Capture phase: runs before Odoo's own click handlers (which open the record).
        listen(root, "click", (ev) => this.jaconOnClick(ev), true);
        listen(document, "pointerdown", (ev) => {
            if (!root.contains(ev.target)) {
                this.jaconClearSelection();
            }
        });
        listen(document, "keydown", (ev) => this.jaconOnKeyDown(ev));
    },

    // -- the cells ------------------------------------------------------------
    /** The cells of the table, read once and kept until the next render. */
    jaconGrid() {
        if (!this.jaconSel.grid) {
            const rows = [];
            const index = new Map();
            const rowElements = this.tableRef.el?.querySelectorAll("tbody tr.o_data_row") || [];
            rowElements.forEach((row, rowIndex) => {
                const cells = [...row.querySelectorAll(CELL_SELECTOR)];
                cells.forEach((cell, col) => index.set(cell, { row: rowIndex, col }));
                rows.push(cells);
            });
            this.jaconSel.grid = { rows, index };
        }
        return this.jaconSel.grid;
    },

    /** {row, col} of a cell element, or null. */
    jaconPositionOf(cell) {
        return (cell && this.jaconGrid().index.get(cell)) || null;
    },

    jaconCellAtPoint(x, y) {
        return document.elementFromPoint(x, y)?.closest(CELL_SELECTOR) || null;
    },

    jaconSignature() {
        return this.props.list.records.map((record) => record.id).join(",");
    },

    // -- mouse ------------------------------------------------------------------
    jaconOnPointerDown(ev) {
        if (ev.button !== 0 || ev.target.closest(IGNORED_TARGETS) || !this.tableRef.el?.contains(ev.target)) {
            return;
        }
        const cell = ev.target.closest(CELL_SELECTOR);
        if (!cell || cell.closest("tr.o_selected_row")) {
            // A header, a group line, a row being edited...: any selection is dropped.
            this.jaconClearSelection();
            return;
        }
        if (ev.shiftKey && this.jaconSel.anchor) {
            return; // handled on click: extends the selection
        }
        this.jaconClearSelection();
        const start = this.jaconPositionOf(cell);
        if (!start) {
            return;
        }
        const { clientX: startX, clientY: startY } = ev;
        const move = (moveEvent) => {
            const far =
                Math.abs(moveEvent.clientX - startX) > DRAG_THRESHOLD ||
                Math.abs(moveEvent.clientY - startY) > DRAG_THRESHOLD;
            if (!this.jaconSel.dragging && !far) {
                return;
            }
            if (!this.jaconSel.dragging) {
                this.jaconSel.dragging = true;
                this.tableRef.el.classList.add("o_jacon_cell_selecting");
                this.jaconSel.anchor = start;
                this.jaconSel.signature = this.jaconSignature();
            }
            window.getSelection()?.removeAllRanges(); // no text highlighted across the rows
            const over = this.jaconPositionOf(this.jaconCellAtPoint(moveEvent.clientX, moveEvent.clientY));
            const focus = over || this.jaconSel.focus || start;
            const current = this.jaconSel.focus;
            if (!current || current.row !== focus.row || current.col !== focus.col) {
                this.jaconSel.focus = focus; // painted only when the end of the range moved to another cell
                this.jaconPaintSelection();
            }
        };
        const stop = () => {
            window.removeEventListener("pointermove", move);
            window.removeEventListener("pointerup", stop);
            window.removeEventListener("pointercancel", stop);
            this.tableRef.el?.classList.remove("o_jacon_cell_selecting");
            if (this.jaconSel.dragging) {
                // The click that follows a drag must not open the record.
                this.jaconSel.swallowClick = true;
                setTimeout(() => (this.jaconSel.swallowClick = false), 0);
            }
            this.jaconSel.dragging = false;
        };
        window.addEventListener("pointermove", move);
        window.addEventListener("pointerup", stop);
        window.addEventListener("pointercancel", stop);
    },

    jaconOnClick(ev) {
        if (this.jaconSel.swallowClick) {
            ev.stopPropagation();
            ev.preventDefault();
            return;
        }
        const cell = ev.target.closest(CELL_SELECTOR);
        if (ev.shiftKey && this.jaconSel.anchor && cell && !ev.target.closest(IGNORED_TARGETS)) {
            const position = this.jaconPositionOf(cell);
            if (position) {
                ev.stopPropagation();
                ev.preventDefault();
                window.getSelection()?.removeAllRanges();
                this.jaconSel.focus = position;
                this.jaconSel.signature = this.jaconSignature();
                this.jaconPaintSelection();
            }
        }
    },

    // -- keyboard -----------------------------------------------------------------
    jaconOnKeyDown(ev) {
        if (!this.jaconSel.anchor) {
            return;
        }
        if (ev.key === "Escape") {
            this.jaconClearSelection();
        } else if ((ev.ctrlKey || ev.metaKey) && (ev.key === "c" || ev.key === "C")) {
            if (ev.target.closest?.(IGNORED_TARGETS) || window.getSelection()?.toString()) {
                return; // text is being edited or highlighted: the browser copies that, not the cells
            }
            ev.preventDefault();
            this.jaconCopySelection();
        }
    },

    // -- painting -------------------------------------------------------------------
    /** [rowFrom, rowTo, colFrom, colTo] of the selection, or null. */
    jaconRange() {
        const { anchor, focus } = this.jaconSel;
        if (!anchor || !focus) {
            return null;
        }
        return [
            Math.min(anchor.row, focus.row),
            Math.max(anchor.row, focus.row),
            Math.min(anchor.col, focus.col),
            Math.max(anchor.col, focus.col),
        ];
    },

    jaconUnpaint() {
        for (const cell of this.jaconSel.painted) {
            cell.classList.remove(SELECTED, ...Object.values(EDGES));
        }
        this.jaconSel.painted = [];
    },

    /** Marks the cells of the range (only those: the ones painted before are cleared, nothing else is read). */
    jaconPaintSelection() {
        this.jaconUnpaint();
        const range = this.jaconRange();
        if (!range) {
            return;
        }
        const [rowFrom, rowTo, colFrom, colTo] = range;
        const { rows } = this.jaconGrid();
        for (let r = rowFrom; r <= rowTo && r < rows.length; r++) {
            for (let c = colFrom; c <= colTo && c < rows[r].length; c++) {
                const classes = [SELECTED];
                if (r === rowFrom) classes.push(EDGES.top);
                if (r === rowTo) classes.push(EDGES.bottom);
                if (c === colFrom) classes.push(EDGES.left);
                if (c === colTo) classes.push(EDGES.right);
                rows[r][c].classList.add(...classes);
                this.jaconSel.painted.push(rows[r][c]);
            }
        }
    },

    jaconClearSelection() {
        if (!this.jaconSel.anchor) {
            return;
        }
        this.jaconSel.anchor = this.jaconSel.focus = null;
        this.jaconUnpaint();
    },

    // -- copying ----------------------------------------------------------------------
    /** What a cell holds as one line of text (tags are joined by commas). */
    jaconCellText(cell) {
        const tags = [...cell.querySelectorAll(".o_tag")];
        const text = tags.length ? tags.map((tag) => tag.textContent.trim()).join(", ") : cell.innerText;
        return text.replace(/\s+/g, " ").trim();
    },

    /** The selection as a grid of text: { header: [titles], rows: [[cell text]] }, or null. */
    jaconSelectionGrid() {
        const range = this.jaconRange();
        if (!range) {
            return null;
        }
        const [rowFrom, rowTo, colFrom, colTo] = range;
        const { rows } = this.jaconGrid();
        // A data cell is drawn for every column of the list, in the same order: the titles come from
        // the columns (not from the header cells, which include selectors and the settings cog).
        const header = this.columns
            .slice(colFrom, colTo + 1)
            .map((column) => (column.label || column.string || "").replace(/\s+/g, " ").trim());
        const lines = [];
        for (let r = rowFrom; r <= rowTo && r < rows.length; r++) {
            lines.push(rows[r].slice(colFrom, colTo + 1).map((cell) => this.jaconCellText(cell)));
        }
        return { header, rows: lines };
    },

    /** Plain text: columns separated by a tab, rows by a new line (what Excel reads as a grid). */
    jaconGridToText({ header, rows }) {
        return [header, ...rows].map((line) => line.join("\t")).join("\n");
    },

    /** A real table, so that Word, Outlook, a mail composer, a wiki... paste it as a table with borders. */
    jaconGridToHtml({ header, rows }) {
        const escape = (text) =>
            text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
        const border = "border:1px solid #999999;padding:3px 6px;";
        const head = header
            .map((title) => `<th style="${border}background-color:#e8eef6;text-align:left;">${escape(title)}</th>`)
            .join("");
        const body = rows
            .map(
                (line) =>
                    "<tr>" + line.map((text) => `<td style="${border}">${escape(text)}</td>`).join("") + "</tr>"
            )
            .join("");
        return (
            '<table style="border-collapse:collapse;font-family:Calibri,Arial,sans-serif;font-size:11pt;" ' +
            `border="1" cellspacing="0" cellpadding="4"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`
        );
    },

    jaconCopySelection() {
        const grid = this.jaconSelectionGrid();
        if (!grid) {
            return;
        }
        const text = this.jaconGridToText(grid);
        const html = this.jaconGridToHtml(grid);
        // The browser's copy command works over plain http too (the clipboard API needs a secure
        // context) and needs no permission. A hidden textarea gives it something to copy; the copy
        // event then puts both the table (HTML) and the plain text on the clipboard: a mail or Word
        // takes the table, Excel and text boxes take the grid of text.
        const active = document.activeElement;
        const box = document.createElement("textarea");
        box.value = text;
        box.setAttribute("readonly", "");
        box.style.cssText = "position:fixed;top:0;left:0;opacity:0;";
        document.body.appendChild(box);
        box.select();
        const onCopy = (copyEvent) => {
            copyEvent.clipboardData.setData("text/html", html);
            copyEvent.clipboardData.setData("text/plain", text);
            copyEvent.preventDefault();
        };
        document.addEventListener("copy", onCopy, true);
        let copied = false;
        try {
            copied = document.execCommand("copy");
        } catch {
            copied = false;
        }
        document.removeEventListener("copy", onCopy, true);
        box.remove();
        active?.focus?.();
        const count = grid.rows.length * grid.header.length;
        this.env.services.notification.add(
            copied ? _t("Copied %s cell(s) as a table. Paste them in Excel, Word or an email.", count) : _t("Could not copy."),
            { type: copied ? "success" : "warning" }
        );
    },
});
