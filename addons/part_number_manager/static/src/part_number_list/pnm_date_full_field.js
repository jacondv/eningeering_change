/** @odoo-module **/

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

// Odoo's own default Date/Datetime display (toLocaleDateString/
// toLocaleDateTimeString in @web/core/l10n/dates.js) deliberately omits
// the year whenever it matches the current year (e.g. "26 Aug" instead of
// "26 Aug 2026") - fine for a chat timestamp, confusing on a data column
// where every row's year should always be visible/comparable. This widget
// always renders "dd MMM yyyy", read-only - no picker, no edit mode
// (Date Created isn't meant to be hand-edited from the list).
export class PnmDateFullField extends Component {
    static template = "part_number_manager.PnmDateFullField";
    static props = { ...standardFieldProps };

    get formattedValue() {
        const value = this.props.record.data[this.props.name];
        return value ? value.toFormat("dd MMM yyyy") : "";
    }
}

registry.category("fields").add("pnm_date_full", { component: PnmDateFullField });
