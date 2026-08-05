import { registry } from "@web/core/registry";
import { DateTimeField, dateField } from "@web/views/fields/datetime/datetime_field";

// Always renders as "5 Aug, 2026" (day before month), regardless of the
// user's language/locale date format - unlike the standard Date widget,
// whose text mode (numeric=false) ignores Settings > Languages > Date
// Format and always follows the browser locale instead.
export class DayMonthDateField extends DateTimeField {
    getFormattedValue(valueIndex, numeric = this.props.numeric) {
        if (numeric) {
            return super.getFormattedValue(valueIndex, numeric);
        }
        const value = this.values[valueIndex];
        if (!value) {
            return "";
        }
        return value.toFormat("d MMM, yyyy");
    }
}

export const dayMonthDateField = {
    ...dateField,
    component: DayMonthDateField,
};

registry.category("fields").add("day_month_date", dayMonthDateField);
