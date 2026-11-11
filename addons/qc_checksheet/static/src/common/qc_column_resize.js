/** @odoo-module **/

import { onMounted, onPatched, useRef } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";

const MIN_WIDTH = 50;
const STORAGE_PREFIX = "qc_checksheet.columns.";

function readWidths(key) {
    try {
        const widths = JSON.parse(browser.localStorage.getItem(STORAGE_PREFIX + key));
        return Array.isArray(widths) ? widths : [];
    } catch {
        return [];
    }
}

function writeWidths(key, widths) {
    try {
        if (widths) {
            browser.localStorage.setItem(STORAGE_PREFIX + key, JSON.stringify(widths));
        } else {
            browser.localStorage.removeItem(STORAGE_PREFIX + key);
        }
    } catch {
        // Storage can be blocked: the widths then last until the page is left.
    }
}

/**
 * Lets the user drag the edge of a column header to set its width, and keeps the widths in this browser.
 * `refName` is the t-ref of the <table>; `key` tells this table's widths from another's. A header with the class
 * o_qce_select_col has no grip. Double-clicking a grip forgets every width of the table.
 */
export function useColumnResize(key, refName = "resizable") {
    const ref = useRef(refName);

    const headers = () => [...(ref.el?.querySelectorAll("thead th") || [])];

    /** Fixed layout, the table as wide as its columns, so that a column keeps the width it was given. */
    function apply(widths) {
        const table = ref.el;
        if (!table) {
            return;
        }
        const ths = headers();
        if (!widths.length) {
            table.style.tableLayout = "";
            table.style.width = "";
            table.style.minWidth = "";
            ths.forEach((th) => (th.style.width = ""));
            return;
        }
        table.style.tableLayout = "fixed";
        let total = 0;
        ths.forEach((th, index) => {
            const width = widths[index] || th.offsetWidth;
            th.style.width = `${width}px`;
            total += width;
        });
        table.style.width = `${total}px`;
        table.style.minWidth = "0";
    }

    function startDrag(event, index) {
        event.preventDefault();
        event.stopPropagation();
        // Every column is fixed at what it is now, so that only the one dragged moves.
        const widths = headers().map((th) => Math.round(th.getBoundingClientRect().width));
        const startX = event.clientX;
        const startWidth = widths[index];
        apply(widths);
        const onMove = (move) => {
            widths[index] = Math.max(MIN_WIDTH, Math.round(startWidth + move.clientX - startX));
            apply(widths);
        };
        const onUp = () => {
            window.removeEventListener("mousemove", onMove);
            window.removeEventListener("mouseup", onUp);
            writeWidths(key, widths);
        };
        window.addEventListener("mousemove", onMove);
        window.addEventListener("mouseup", onUp);
    }

    function reset() {
        writeWidths(key, null);
        apply([]);
    }

    /** The grip on each header's right edge; added again after a render took it away. */
    function addGrips() {
        headers().forEach((th, index) => {
            if (th.classList.contains("o_qce_select_col") || th.querySelector(":scope > .o_qce_grip")) {
                return;
            }
            const grip = document.createElement("span");
            grip.className = "o_qce_grip";
            grip.title = "Drag to resize. Double-click to reset every column.";
            grip.addEventListener("mousedown", (event) => startDrag(event, index));
            grip.addEventListener("dblclick", (event) => {
                event.stopPropagation();
                reset();
            });
            th.appendChild(grip);
        });
    }

    onMounted(() => {
        addGrips();
        const widths = readWidths(key);
        // Only widths kept for this many columns: the table may have changed since.
        if (widths.length && widths.length === headers().length) {
            apply(widths);
        }
    });
    onPatched(addGrips);
}
