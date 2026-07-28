import { registry } from "@web/core/registry";
import { CharField, charField } from "@web/views/fields/char/char_field";

export class TaskNameIndentField extends CharField {
    static template = "project_custom_views.TaskNameIndentField";
}

export const taskNameIndentField = {
    ...charField,
    component: TaskNameIndentField,
    fieldDependencies: [
        { name: "subtask_count", type: "integer" },
        { name: "closed_subtask_count", type: "integer" },
        { name: "hierarchy_depth", type: "integer" },
    ],
};

registry.category("fields").add("task_name_indent", taskNameIndentField);
