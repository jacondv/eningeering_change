import { registry } from "@web/core/registry";
import { browser } from "@web/core/browser/browser";
import { onMounted, useEffect } from "@odoo/owl";
import { projectProjectListView } from "@project/views/project_project_list/project_project_list_view";
import { projectTaskListView } from "@project/views/project_task_list/project_task_list_view";

// Wraps a List Renderer so that column widths the user drags-to-resize are
// saved to localStorage (keyed by model) and re-applied after every render,
// surviving a browser refresh. Odoo's own drag-resize (useMagicColumnWidths)
// only keeps widths in memory for the current page load - this layers
// persistence on top without touching that core hook.
function withResizableColumnMemory(BaseRenderer) {
    return class extends BaseRenderer {
        setup() {
            super.setup();
            useEffect(() => {
                this.enableButtonColumnResize();
                this.restoreColumnWidths();
            });
            onMounted(() => {
                this.tableRef.el?.addEventListener("pointerup", () => this.saveColumnWidths());
            });
        }

        // Odoo's list header template only draws a drag handle on `field`
        // columns (see web.ListRenderer's <th t-if="column.type === 'field'">
        // vs the plain <th t-else=""/> used for button columns like our
        // "Tasks" button) - button columns get a width but no way to drag
        // it. Since that template is shared by every list view in the app,
        // patching it would resize buttons everywhere; instead we add the
        // same handle imperatively, scoped to just these renderer instances.
        enableButtonColumnResize() {
            const table = this.tableRef.el;
            const headerRow = table?.querySelector("thead tr");
            if (!headerRow) {
                return;
            }
            const headers = [...headerRow.children];
            const offset = this.hasSelectors ? 1 : 0;
            this.columns.forEach((column, index) => {
                if (column.type === "field") {
                    return;
                }
                const th = headers[offset + index];
                if (!th || th.dataset.jaconResizable) {
                    return;
                }
                th.dataset.jaconResizable = "1";
                th.dataset.name = column.name || `button_${index}`;
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
        }

        get columnWidthsStorageKey() {
            return `jacon_core.list_column_widths.${this.props.list.resModel}`;
        }

        saveColumnWidths() {
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
                browser.localStorage.setItem(this.columnWidthsStorageKey, JSON.stringify(widths));
            }
        }

        restoreColumnWidths() {
            const saved = browser.localStorage.getItem(this.columnWidthsStorageKey);
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
            for (const th of table.querySelectorAll("thead th[data-name]")) {
                const width = widths[th.dataset.name];
                if (width) {
                    th.style.width = width;
                }
            }
        }
    };
}

export const jaconCoreProjectListView = {
    ...projectProjectListView,
    Renderer: withResizableColumnMemory(projectProjectListView.Renderer),
};
registry.category("views").add("jacon_core_project_list", jaconCoreProjectListView);

export const jaconCoreTaskListView = {
    ...projectTaskListView,
    Renderer: withResizableColumnMemory(projectTaskListView.Renderer),
};
registry.category("views").add("jacon_core_task_list", jaconCoreTaskListView);
