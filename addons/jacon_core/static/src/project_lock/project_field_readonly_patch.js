import { patch } from "@web/core/utils/patch";
import { Field } from "@web/views/fields/field";

// Force every field readonly on an existing project.project record until
// it's been unlocked (see project_edit_lock_field.js / models/project_project.py
// is_unlocked). Patching this single getter - rather than touching each
// field individually in the view, which would mean overriding dozens of
// fields spread across several addons (project, sale_project,
// sale_timesheet, ...) - is the only place in the form-rendering pipeline
// where a field's final readonly state is resolved, and it's scoped to
// project.project only (checked inside the getter), so no other model's
// fields are affected anywhere else in the system.
patch(Field.prototype, {
    get fieldComponentProps() {
        const props = super.fieldComponentProps;
        const record = this.props.record;
        if (
            record.resModel === "project.project" &&
            record.resId &&
            !record.data.is_unlocked &&
            this.props.name !== "is_unlocked"
        ) {
            return { ...props, readonly: true };
        }
        return props;
    },
});
