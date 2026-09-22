/** @odoo-module **/

import { registry } from "@web/core/registry";
import { MonetaryField, monetaryField } from "@web/views/fields/monetary/monetary_field";
import { insertThousandsSep } from "@web/core/utils/numbers";
import { localization } from "@web/core/l10n/localization";
import { nbsp } from "@web/core/utils/strings";

// VND amounts read faster abbreviated to the nearest thousand - e.g.
// 18,540,934 -> "18,541k" - than every digit spelled out. Deliberately a
// fixed /1000 + "k", not Odoo's own humanNumber() (which auto-escalates to
// M/G/... and would turn this same value into "19M", losing the precision
// actually wanted at a glance). VND-only on purpose - USD/AUD amounts are
// already small enough (2 decimals, rarely 4+ digits) that abbreviating
// them would lose precision for no readability gain. Read-only display
// only (list cell not being edited, or a readonly form field) - while
// actively editing a cell it falls back to the normal exact MonetaryField
// value, since abbreviated text isn't something you can type a precise
// price into.
const ABBREVIATED_CURRENCIES = ['VND'];

export class PnmMonetaryThousandsField extends MonetaryField {
    get formattedValue() {
        if (this.props.readonly && this.value !== false && Math.abs(this.value) >= 1000
                && this.currency && ABBREVIATED_CURRENCIES.includes(this.currency.name)) {
            const thousands = Math.round(this.value / 1000);
            const { thousandsSep, grouping } = localization;
            const formatted = insertThousandsSep(String(thousands), thousandsSep, grouping) + "k";
            return this.currencySymbol ? `${formatted}${nbsp}${this.currencySymbol}` : formatted;
        }
        return super.formattedValue;
    }
}

export const pnmMonetaryThousandsField = {
    ...monetaryField,
    component: PnmMonetaryThousandsField,
};

registry.category("fields").add("pnm_monetary_thousands", pnmMonetaryThousandsField);
