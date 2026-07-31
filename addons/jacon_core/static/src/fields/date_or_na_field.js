import { registry } from "@web/core/registry";
import { DateTimeField, dateField } from "@web/views/fields/datetime/datetime_field";

export class DateOrNaField extends DateTimeField {
    static template = "jacon_core.DateOrNaField";
}

export const dateOrNaField = {
    ...dateField,
    component: DateOrNaField,
};

registry.category("fields").add("date_or_na", dateOrNaField);
