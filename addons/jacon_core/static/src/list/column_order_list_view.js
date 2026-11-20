import { patch } from "@web/core/utils/patch";
import { browser } from "@web/core/browser/browser";
import { useState } from "@odoo/owl";
import { ListRenderer } from "@web/views/list/list_renderer";

/**
 * Lets the user choose which columns of a list are shown and in which order, opt-in per list.
 *
 * Add `class="o_jacon_column_order"` to the <list> tag of a view. The settings menu at the end of the
 * header (the cog) then lists every column on one line: a check box (shown / hidden - only for the
 * optional columns, the others are always shown), its title, and up / down buttons. "Reset order" puts
 * them back. The order is remembered in this browser, per model; what is shown or hidden is remembered
 * by Odoo itself.
 *
 * Odoo builds the columns it draws in getActiveColumns() on every render, and the header, the rows,
 * the totals and the keyboard moves all read that one list: sorting it is enough. Columns that are
 * not fields (buttons) and the row-handle column keep their place; the fields are sorted among
 * themselves. A column that is not in the saved order (a new one) goes after the others.
 */
const OPT_IN_CLASS = "o_jacon_column_order";

const isMovable = (column) => column.type === "field" && column.widget !== "handle";

patch(ListRenderer.prototype, {
    setup() {
        super.setup();
        // Reactive: changing the order re-renders the list and the open menu at once.
        this.jaconOrder = useState({ names: this.jaconLoadOrder() });
    },

    get jaconColumnOrderEnabled() {
        return (this.props.archInfo?.className || "").split(/\s+/).includes(OPT_IN_CLASS);
    },

    // The cog is shown even when the list has no optional column, as the order lives in its menu.
    get displayOptionalFields() {
        return super.displayOptionalFields || this.jaconColumnOrderEnabled;
    },

    // Our menu lists every column with its check box, so Odoo's own list of optional columns is not
    // repeated above it.
    get optionalFieldGroups() {
        return this.jaconColumnOrderEnabled ? [] : super.optionalFieldGroups;
    },

    // Per model and per view: another list of the same model, with other columns, has its own order.
    get jaconOrderStorageKey() {
        return `jacon_core.list_column_order.${this.props.list.resModel}.${this.env.config?.viewId || "default"}`;
    },

    jaconLoadOrder() {
        try {
            const saved = JSON.parse(browser.localStorage.getItem(this.jaconOrderStorageKey));
            return Array.isArray(saved) ? saved.filter((name) => typeof name === "string") : [];
        } catch {
            return [];
        }
    },

    /** The movable columns of `columns` in the saved order; the others stay where they are. */
    jaconSortColumns(columns) {
        const saved = this.jaconOrder.names;
        if (!saved.length) {
            return columns;
        }
        const rank = (column) => {
            const index = saved.indexOf(column.name);
            return index === -1 ? saved.length : index;
        };
        const sorted = columns
            .filter(isMovable)
            .map((column, position) => ({ column, position }))
            .sort((a, b) => rank(a.column) - rank(b.column) || a.position - b.position)
            .map(({ column }) => column);
        let next = 0;
        return columns.map((column) => (isMovable(column) ? sorted[next++] : column));
    },

    getActiveColumns() {
        const columns = super.getActiveColumns();
        return this.jaconColumnOrderEnabled ? this.jaconSortColumns(columns) : columns;
    },

    /** What the menu lists: every column that can be shown, shown or not, in the order they are drawn. */
    get jaconMenuColumns() {
        const columns = this.allColumns.filter(
            (column) => isMovable(column) && !this.evalColumnInvisible(column.column_invisible)
        );
        return this.jaconSortColumns(columns);
    },

    /** Optional columns can be hidden; the others are always shown. */
    jaconColumnShown(column) {
        return !column.optional || !!this.optionalActiveFields[column.name];
    },

    jaconColumnLabel(column) {
        return column.label || column.string || column.name;
    },

    jaconMoveColumn(column, step) {
        const columns = this.jaconMenuColumns;
        const names = columns.map((col) => col.name);
        const from = names.indexOf(column.name);
        let to = from + step;
        // A shown column jumps over the hidden ones next to it: the table must visibly change.
        if (this.jaconColumnShown(column)) {
            while (to >= 0 && to < columns.length && !this.jaconColumnShown(columns[to])) {
                to += step;
            }
        }
        if (from < 0 || to < 0 || to >= names.length) {
            return;
        }
        [names[from], names[to]] = [names[to], names[from]];
        this.jaconApplyOrder(names);
    },

    /** Whether the arrow of a column has somewhere to go (the same rule as jaconMoveColumn). */
    jaconCanMove(column, step) {
        const columns = this.jaconMenuColumns;
        let to = columns.findIndex((col) => col.name === column.name) + step;
        if (this.jaconColumnShown(column)) {
            while (to >= 0 && to < columns.length && !this.jaconColumnShown(columns[to])) {
                to += step;
            }
        }
        return to >= 0 && to < columns.length;
    },

    jaconResetColumnOrder() {
        this.jaconApplyOrder([]);
    },

    jaconApplyOrder(names) {
        try {
            if (names.length) {
                browser.localStorage.setItem(this.jaconOrderStorageKey, JSON.stringify(names));
            } else {
                browser.localStorage.removeItem(this.jaconOrderStorageKey);
            }
        } catch {
            // the order is just not remembered
        }
        this.jaconClearSelection?.(); // a selected range of cells means nothing once the columns moved
        this.jaconOrder.names = names;
        this.render(true);
    },
});
