import { patch } from "@web/core/utils/patch";
import { Field } from "@web/views/fields/field";

// Force every field readonly on an existing part_number_manager.part_number
// record until it's been unlocked (see part_number_edit_lock_field.js /
// models/part_number.py is_unlocked). Scoped to part_number_manager.part_number
// only (checked inside the getter), so no other model's fields are affected.
//
// `isDisabled` is also forced here, not just `readonly`: StatusBarField (the
// `state` field's widget) ignores the generic `readonly` prop entirely - its
// buttons' `disabled` attribute is driven solely by `props.isDisabled`
// (computed by its own extractProps from the view's readonly condition,
// before this getter's override ever runs) - so without also overriding
// `isDisabled` here, the state buttons would stay clickable while every
// other field on the form is correctly locked.
patch(Field.prototype, {
    get fieldComponentProps() {
        const props = super.fieldComponentProps;
        const record = this.props.record;
        if (
            record.resModel === "part_number_manager.part_number" &&
            record.resId &&
            !record.data.is_unlocked &&
            this.props.name !== "is_unlocked"
        ) {
            return { ...props, readonly: true, isDisabled: true };
        }
        return props;
    },
});
