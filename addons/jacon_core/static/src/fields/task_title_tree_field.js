import { registry } from "@web/core/registry";
import { taskHierarchyFieldDependencies } from "@project_custom_views/fields/task_name_indent_field";
import {
    TaskTitleAutocompleteField,
    taskTitleAutocompleteField,
} from "./task_title_autocomplete_field";

// Title autocomplete for a list of tasks shown as a tree: indented by depth,
// with the sub-task count next to the title, same as the Tasks list view
// (see project_custom_views' task_name_indent).
export class TaskTitleTreeField extends TaskTitleAutocompleteField {
    static template = "jacon_core.TaskTitleTreeField";
}

registry.category("fields").add("task_title_tree", {
    ...taskTitleAutocompleteField,
    component: TaskTitleTreeField,
    fieldDependencies: taskHierarchyFieldDependencies,
});
