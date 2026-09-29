import { registry } from "@web/core/registry";
import { DateTimeField, dateTimeField } from "@web/views/fields/datetime/datetime_field";

// Datetime shown compactly as "09-Sep, 26"; picking still uses the standard calendar.
export class DateTimeShortField extends DateTimeField {
    getFormattedValue(valueIndex) {
        const value = this.values[valueIndex];
        return value ? value.toFormat("dd-LLL, yy") : "";
    }
}

registry.category("fields").add("datetime_short", {
    ...dateTimeField,
    component: DateTimeShortField,
});
