import { onMounted, onWillUnmount, useEffect } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";

/**
 * Excel-like selection of cells in the tables of the dashboard (the tables with the class o_em_table):
 *   - press on a cell and drag: the rectangle of cells under the mouse is selected;
 *   - Shift+click a cell: extends the selection (in the same table);
 *   - Ctrl+C: copies the cells with the titles of their columns, as a table (HTML, for a mail or Word)
 *     and as text with tabs (for Excel);
 *   - Esc, or a click elsewhere: clears the selection.
 * A plain click (no drag) works as before: it still picks the Group / Family / Model or opens the Job.
 * One selection at a time, in one table. Used by the dashboard only.
 *
 * `getVersion()` returns the things the tables are drawn from (a list): when any of them changes the
 * tables are drawn again and the range means nothing, so it is dropped. The dashboard also calls the
 * returned `clear()` when it changes the columns.
 */
const TABLE = "table.o_em_table";
const DRAG_THRESHOLD = 4; // px the mouse must move before a press counts as a drag
const IGNORED_TARGETS = "input, textarea, select, button";
const EDGE_CLASSES = ["o_em_cs_top", "o_em_cs_bottom", "o_em_cs_left", "o_em_cs_right"];
const SELECTED = "o_em_cell_selected";

const cleanText = (text) => text.replace(/\s+/g, " ").trim();

const escapeHtml = (text) =>
    text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

const sameVersion = (a, b) => a.length === b.length && a.every((item, index) => item === b[index]);

export function useCellSelect(rootRef, getVersion = () => []) {
    const notification = useService("notification");
    const sel = {
        table: null,
        anchor: null, // {row, col}
        focus: null,
        version: [],
        painted: [],
        swallowClick: false,
        cleanups: [],
    };
    // The data rows of each table, read once until the next render: { rows: [tr], index: Map(tr -> position) }.
    let rowsCache = new Map();

    /** The rows that hold data (not the "No ... matches" line), with their position. */
    function rowsOf(table) {
        let entry = rowsCache.get(table);
        if (!entry) {
            const rows = [...table.querySelectorAll("tbody tr:not(.o_em_empty)")];
            entry = { rows, index: new Map(rows.map((row, position) => [row, position])) };
            rowsCache.set(table, entry);
        }
        return entry;
    }

    // -- painting -------------------------------------------------------------
    const range = () =>
        sel.anchor && sel.focus
            ? [
                  Math.min(sel.anchor.row, sel.focus.row),
                  Math.max(sel.anchor.row, sel.focus.row),
                  Math.min(sel.anchor.col, sel.focus.col),
                  Math.max(sel.anchor.col, sel.focus.col),
              ]
            : null;

    function unpaint() {
        for (const cell of sel.painted) {
            cell.classList.remove(SELECTED, ...EDGE_CLASSES);
        }
        sel.painted = [];
    }

    function paint() {
        unpaint();
        const bounds = range();
        if (!bounds || !sel.table) {
            return;
        }
        const [rowFrom, rowTo, colFrom, colTo] = bounds;
        const { rows } = rowsOf(sel.table);
        for (let r = rowFrom; r <= rowTo && r < rows.length; r++) {
            const cells = rows[r].children;
            for (let c = colFrom; c <= colTo && c < cells.length; c++) {
                const classes = [SELECTED];
                if (r === rowFrom) classes.push("o_em_cs_top");
                if (r === rowTo) classes.push("o_em_cs_bottom");
                if (c === colFrom) classes.push("o_em_cs_left");
                if (c === colTo) classes.push("o_em_cs_right");
                cells[c].classList.add(...classes);
                sel.painted.push(cells[c]);
            }
        }
    }

    function clear() {
        if (!sel.anchor) {
            return;
        }
        sel.anchor = sel.focus = null;
        sel.table = null;
        unpaint();
    }

    // After every render the tables may have been drawn again: read the rows anew, and drop the range
    // when what the tables show has changed. With no selection nothing is touched (one cheap comparison).
    useEffect(() => {
        rowsCache = new Map();
        if (sel.anchor && (!sel.table?.isConnected || !sameVersion(sel.version, getVersion()))) {
            clear();
        } else if (sel.anchor) {
            paint(); // the cells may have been replaced: mark the current ones
        }
    });

    // -- where a cell is ------------------------------------------------------------
    /** {table, row, col} of a data cell of one of the dashboard's tables, or null. */
    function positionOf(element) {
        const cell = element?.closest?.("td");
        const rowElement = cell?.parentElement;
        const table = cell?.closest(TABLE);
        if (!table || !rowElement?.closest("tbody") || rowElement.classList.contains("o_em_empty")) {
            return null;
        }
        const row = rowsOf(table).index.get(rowElement);
        return row === undefined ? null : { table, row, col: cell.cellIndex };
    }

    // -- mouse ------------------------------------------------------------------------
    function onPointerDown(ev) {
        if (ev.button !== 0 || ev.target.closest(IGNORED_TARGETS)) {
            return;
        }
        const start = positionOf(ev.target);
        if (!start) {
            clear(); // a header, a title, empty space...
            return;
        }
        if (ev.shiftKey) {
            // Extends a range of this table (done on click); with none, it is a plain click.
            if (!sel.anchor || sel.table !== start.table) {
                clear();
            }
            return;
        }
        clear();
        const root = rootRef.el;
        let dragging = false;
        let lastCell = null;
        let frame = 0;
        let pending = null; // the last pointer position, handled once per frame
        const handle = () => {
            frame = 0;
            const { clientX, clientY } = pending;
            const cell = document.elementFromPoint(clientX, clientY)?.closest("td");
            if (!cell || cell === lastCell) {
                return; // painted only when the end of the range moves to another cell
            }
            lastCell = cell;
            const over = positionOf(cell);
            if (over && over.table === sel.table) {
                sel.focus = { row: over.row, col: over.col };
                paint();
            }
        };
        const move = (moveEvent) => {
            if (!dragging) {
                const far =
                    Math.abs(moveEvent.clientX - ev.clientX) > DRAG_THRESHOLD ||
                    Math.abs(moveEvent.clientY - ev.clientY) > DRAG_THRESHOLD;
                if (!far) {
                    return;
                }
                dragging = true;
                root.classList.add("o_em_selecting"); // no text is highlighted across the rows from here on
                window.getSelection()?.removeAllRanges();
                sel.table = start.table;
                sel.anchor = { row: start.row, col: start.col };
                sel.version = getVersion();
            }
            pending = moveEvent;
            if (!frame) {
                frame = requestAnimationFrame(handle);
            }
        };
        const stop = () => {
            window.removeEventListener("pointermove", move);
            window.removeEventListener("pointerup", stop);
            window.removeEventListener("pointercancel", stop);
            cancelAnimationFrame(frame);
            root?.classList.remove("o_em_selecting");
            if (dragging) {
                // The click that follows a drag must not pick a Group / Family / Model or open a Job.
                sel.swallowClick = true;
                setTimeout(() => (sel.swallowClick = false), 0);
            }
        };
        window.addEventListener("pointermove", move);
        window.addEventListener("pointerup", stop);
        window.addEventListener("pointercancel", stop);
    }

    function onClick(ev) {
        if (sel.swallowClick) {
            ev.stopPropagation();
            ev.preventDefault();
            return;
        }
        if (!ev.shiftKey || !sel.anchor || ev.target.closest(IGNORED_TARGETS)) {
            return;
        }
        const position = positionOf(ev.target);
        if (position && position.table === sel.table) {
            ev.stopPropagation();
            ev.preventDefault();
            window.getSelection()?.removeAllRanges();
            sel.focus = { row: position.row, col: position.col };
            sel.version = getVersion();
            paint();
        }
    }

    // -- keyboard ------------------------------------------------------------------------
    function onKeyDown(ev) {
        if (!sel.anchor) {
            return;
        }
        if (ev.key === "Escape") {
            clear();
        } else if ((ev.ctrlKey || ev.metaKey) && (ev.key === "c" || ev.key === "C")) {
            const active = document.activeElement;
            const outside = active && active !== document.body && !rootRef.el?.contains(active);
            if (outside || ev.target.closest?.(IGNORED_TARGETS) || window.getSelection()?.toString()) {
                return; // a dialog, a field being edited or text being highlighted: the browser copies that
            }
            ev.preventDefault();
            copy();
        }
    }

    // -- copying ---------------------------------------------------------------------------
    /** The selection as { header: [titles], rows: [[text]] }, or null. */
    function selectionGrid() {
        const bounds = range();
        if (!bounds || !sel.table) {
            return null;
        }
        const [rowFrom, rowTo, colFrom, colTo] = bounds;
        // The titles and the cells line up one to one (a column shown or not shows its title and its cells).
        const header = [...sel.table.querySelectorAll("thead th")]
            .slice(colFrom, colTo + 1)
            .map((th) => cleanText(th.textContent));
        // textContent, not innerText: innerText makes the browser lay the page out again for every cell.
        const rows = rowsOf(sel.table)
            .rows.slice(rowFrom, rowTo + 1)
            .map((row) => [...row.children].slice(colFrom, colTo + 1).map((cell) => cleanText(cell.textContent)));
        return { header, rows };
    }

    function gridToText({ header, rows }) {
        return [header, ...rows].map((line) => line.join("\t")).join("\n");
    }

    /** A real table, so that Word, Outlook, a mail composer... paste it as a table with borders. */
    function gridToHtml({ header, rows }) {
        const border = "border:1px solid #999999;padding:3px 6px;";
        const head = header
            .map((title) => `<th style="${border}background-color:#e8eef6;text-align:left;">${escapeHtml(title)}</th>`)
            .join("");
        const body = rows
            .map((line) => "<tr>" + line.map((text) => `<td style="${border}">${escapeHtml(text)}</td>`).join("") + "</tr>")
            .join("");
        return (
            '<table style="border-collapse:collapse;font-family:Calibri,Arial,sans-serif;font-size:11pt;" ' +
            `border="1" cellspacing="0" cellpadding="4"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`
        );
    }

    function copy() {
        const grid = selectionGrid();
        if (!grid) {
            return;
        }
        const text = gridToText(grid);
        const html = gridToHtml(grid);
        // The browser's copy command works over plain http too (the clipboard API needs a secure
        // context). A hidden textarea gives it something to copy; the copy event then puts both the table
        // (HTML) and the plain text on the clipboard.
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
        notification.add(
            copied ? _t("Copied %s cell(s) as a table. Paste them in Excel, Word or an email.", count) : _t("Could not copy."),
            { type: copied ? "success" : "warning" }
        );
    }

    // -- wiring ---------------------------------------------------------------------------------
    onMounted(() => {
        const root = rootRef.el;
        if (!root) {
            return;
        }
        const listen = (target, type, handler, capture = false) => {
            target.addEventListener(type, handler, capture);
            sel.cleanups.push(() => target.removeEventListener(type, handler, capture));
        };
        listen(root, "pointerdown", onPointerDown);
        listen(root, "click", onClick, true); // before the row's own click (which picks / opens)
        listen(document, "pointerdown", (ev) => {
            if (!root.contains(ev.target)) {
                clear();
            }
        });
        listen(document, "keydown", onKeyDown);
    });
    onWillUnmount(() => sel.cleanups.forEach((cleanup) => cleanup()));

    return { clear };
}
