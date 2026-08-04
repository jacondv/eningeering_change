import { registry } from "@web/core/registry";
import { onMounted } from "@odoo/owl";
import { projectProjectListView } from "@project/views/project_project_list/project_project_list_view";
import { projectTaskListView } from "@project/views/project_task_list/project_task_list_view";

// Odoo right-aligns numeric-typed columns by default. Left-align them (and
// darken the zebra striping a bit) on just the Project/Task lists - see
// left_align_number_list_view.scss for the actual rules, gated on the
// "o_jacon_core_left_align_list" class added here. Column resizing itself
// is handled separately, globally, by resizable_column_list_view.js - it
// no longer needs this js_class to opt in.
function withLeftAlignedNumberColumns(BaseRenderer) {
    return class extends BaseRenderer {
        setup() {
            super.setup();
            onMounted(() => {
                this.tableRef.el?.classList.add("o_jacon_core_left_align_list");
            });
        }
    };
}

export const jaconCoreProjectListView = {
    ...projectProjectListView,
    Renderer: withLeftAlignedNumberColumns(projectProjectListView.Renderer),
};
registry.category("views").add("jacon_core_project_list", jaconCoreProjectListView);

export const jaconCoreTaskListView = {
    ...projectTaskListView,
    Renderer: withLeftAlignedNumberColumns(projectTaskListView.Renderer),
};
registry.category("views").add("jacon_core_task_list", jaconCoreTaskListView);
