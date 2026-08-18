import { registry } from "@web/core/registry";
import { Component } from "@odoo/owl";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { AutoComplete } from "@web/core/autocomplete/autocomplete";
import { useService } from "@web/core/utils/hooks";

// Char/text field variant for project.task's Title: as the user types,
// suggests titles from tasks already created before (see
// project.task.search_task_title_suggestions) so a recurring task name can
// be reused with one click instead of retyped slightly differently every
// time.
export class TaskTitleAutocompleteField extends Component {
    static template = "jacon_core.TaskTitleAutocompleteField";
    static components = { AutoComplete };
    static props = { ...standardFieldProps, placeholder: { type: String, optional: true } };

    setup() {
        this.orm = useService("orm");
    }

    get value() {
        return this.props.record.data[this.props.name] || "";
    }

    get sources() {
        return [{ options: (query) => this.loadOptions(query) }];
    }

    async loadOptions(query) {
        if (!query || query.trim().length < 2) {
            return [];
        }
        const suggestions = await this.orm.call("project.task", "search_task_title_suggestions", [query.trim()]);
        return suggestions.map((suggestion) => ({
            label: suggestion.name,
            onSelect: () => this.selectSuggestion(suggestion),
        }));
    }

    selectSuggestion(suggestion) {
        const values = { [this.props.name]: suggestion.name };
        // Always fills Task Type in from the suggestion when it has one -
        // picking a suggested title is a deliberate "reuse this task" action,
        // so its Task Type should come along with it, overwriting whatever
        // was set before. Only guarded by whether the record actually has
        // that field (this widget is generic - supportedTypes char/text -
        // so it could in principle be reused on a model without it).
        if ('task_type' in this.props.record.data && suggestion.task_type) {
            values.task_type = suggestion.task_type;
        }
        this.props.record.update(values);
    }

    onInput({ inputValue }) {
        this.props.record.update({ [this.props.name]: inputValue });
    }
}

export const taskTitleAutocompleteField = {
    component: TaskTitleAutocompleteField,
    supportedTypes: ["char", "text"],
    extractProps: ({ placeholder }) => ({ placeholder }),
};

registry.category("fields").add("task_title_autocomplete", taskTitleAutocompleteField);
