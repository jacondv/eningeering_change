import { patch } from "@web/core/utils/patch";
import { browser } from "@web/core/browser/browser";
import { onMounted, useEffect } from "@odoo/owl";
import { ListRenderer } from "@web/views/list/list_renderer";

// Patches the core ListRenderer directly (rather than registering opt-in
// per-model view variants) so every list view, in every module, remembers
// column widths the user drags-to-resize - keyed by model, persisted to
// localStorage, and re-applied after every render, surviving a browser
// refresh. Odoo's own drag-resize (useMagicColumnWidths) only keeps widths
// in memory for the current page load - this layers persistence on top
// without touching that core hook, and requires no per-view js_class.
patch(ListRenderer.prototype, {
    // Odoo's own "auto-fit" logic (useMagicColumnWidths) recomputes what it
    // considers the ideal widths on every render and force-applies them -
    // it has no idea we've restored the user's saved widths via direct DOM
    // writes, so any later render (e.g. just starting a drag) made it snap
    // everything back to its own defaults. Turning this off hands width
    // control entirely to the user's drags + our persistence, so nothing
    // fights over it. The `columnWidths` API (onStartResize, resizing,
    // resetWidths) still works either way - this flag only gates the
    // automatic recompute-on-render behavior.
    setup() {
        super.setup();
        useEffect(() => {
            this.jaconEnableMissingColumnResize();
            this.jaconRestoreColumnWidths();
        });
        onMounted(() => {
            this.tableRef.el?.addEventListener("pointerup", () => this.jaconSaveColumnWidths());
        });
    },

    // Odoo's list header template only draws a drag handle when
    // `column.type === 'field' and column.hasLabel` (see web.ListRenderer's
    // <th t-if="column.type === 'field'"> and the nested
    // <t t-if="column.hasLabel and column.widget !== 'handle'"> wrapping the
    // handle span). That skips two kinds of columns: button columns (not
    // type='field'), and nolabel="1" field columns (hasLabel=false) - both
    // get a width but no way to drag it, so the same handle is added
    // imperatively here for those.
    jaconEnableMissingColumnResize() {
        const table = this.tableRef.el;
        const headerRow = table?.querySelector("thead tr");
        if (!headerRow) {
            return;
        }
        const headers = [...headerRow.children];
        const offset = this.hasSelectors ? 1 : 0;
        this.columns.forEach((column, index) => {
            if (column.widget === "handle") {
                // The drag-to-reorder column: core deliberately leaves this
                // one out of resizing, keep it that way.
                return;
            }
            const hasNativeHandle = column.type === "field" && column.hasLabel;
            if (hasNativeHandle) {
                return;
            }
            const th = headers[offset + index];
            if (!th || th.dataset.jaconResizable) {
                return;
            }
            th.dataset.jaconResizable = "1";
            if (!th.dataset.name) {
                th.dataset.name = column.name || `col_${index}`;
            }
            th.classList.add("position-relative");
            const handle = document.createElement("span");
            handle.className =
                "o_resize position-absolute top-0 end-0 bottom-0 ps-1 bg-black-25 opacity-0 opacity-50-hover z-1";
            handle.addEventListener("pointerdown", (ev) => {
                ev.stopPropagation();
                ev.preventDefault();
                this.columnWidths.onStartResize(ev);
            });
            handle.addEventListener("dblclick", () => this.columnWidths.resetWidths());
            th.appendChild(handle);
        });
    },

    get jaconColumnWidthsStorageKey() {
        return `jacon_core.list_column_widths.${this.props.list.resModel}`;
    },

    jaconSaveColumnWidths() {
        const table = this.tableRef.el;
        if (!table) {
            return;
        }
        const widths = {};
        for (const th of table.querySelectorAll("thead th[data-name]")) {
            if (th.style.width) {
                widths[th.dataset.name] = th.style.width;
            }
        }
        if (Object.keys(widths).length) {
            browser.localStorage.setItem(this.jaconColumnWidthsStorageKey, JSON.stringify(widths));
        }
    },

    jaconRestoreColumnWidths() {
        const saved = browser.localStorage.getItem(this.jaconColumnWidthsStorageKey);
        if (!saved) {
            return;
        }
        let widths;
        try {
            widths = JSON.parse(saved);
        } catch {
            return;
        }
        const table = this.tableRef.el;
        if (!table) {
            return;
        }
        table.style.tableLayout = "fixed";
        for (const th of table.querySelectorAll("thead th[data-name]")) {
            const width = widths[th.dataset.name];
            if (width) {
                th.style.width = width;
            }
        }
    },
});

ListRenderer.useMagicColumnWidths = false;
