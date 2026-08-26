/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, onWillStart, onWillUpdateProps, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { PnmCombobox } from "@part_number_manager/part_management_page/pnm_combobox";

const PART_NUMBER_MODEL = "part_number_manager.part_number";

// Many2one editor for the All Lines list: shows and searches by the target
// Part's display_description - never its raw part_number code - using the
// same dropdown component and convention as the Hose & Fitting Builder page.
// The Part Type to offer comes from options="{'part_type': 'Hose'}" on the
// <field> tag (mirrors the field's own domain in job_hose_line.py); options
// are loaded once per column rather than relying on Many2one's built-in
// name_search, since that searches/displays by part_number.
export class PnmDisplayMany2oneField extends Component {
    static template = "hose_fitting_manager.PnmDisplayMany2oneField";
    static components = { PnmCombobox };
    static props = {
        ...standardFieldProps,
        partType: { type: String, optional: true },
        showPartNumber: { type: Boolean, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.state = useState({ options: [], text: this._labelFromRecord(this.props) });

        onWillStart(() => this._loadOptions());
        onWillUpdateProps((nextProps) => {
            // List view row components can be reused across records on
            // re-render - resync the shown text when that happens.
            const curId = this._idFromRecord(this.props);
            const nextId = this._idFromRecord(nextProps);
            if (curId !== nextId) {
                this.state.text = this._labelFromId(nextId) || this._labelFromRecord(nextProps);
            }
        });
    }

    _idFromRecord(props) {
        const value = props.record.data[props.name];
        return value ? value.id : false;
    }

    _labelFromId(id) {
        if (!id) return "";
        const opt = this.state.options.find((o) => o.id === id);
        return opt ? opt.label : "";
    }

    _labelFromRecord(props) {
        // Best-effort initial text before options finish loading - falls
        // back to whatever Odoo already prefetched (the raw part_number),
        // corrected the instant _loadOptions resolves.
        const value = props.record.data[props.name];
        return value ? value.display_name : "";
    }

    get currentId() {
        return this._idFromRecord(this.props);
    }

    async _loadOptions() {
        const domain = this.props.partType ? [["part_type_id.name", "=", this.props.partType]] : [];
        const parts = await this.orm.searchRead(
            PART_NUMBER_MODEL, domain, ["display_description", "short_description", "part_number"]
        );
        // Never dropped even when undescribed - an option missing here
        // reads as "gone", not "needs a description" (see the Builder
        // page's identical fallback in builder.js's _loadConfigs).
        this.state.options = parts.map((p) => {
            const desc = p.display_description || p.short_description || `(No description) ${p.part_number}`;
            return {
                id: p.id,
                // Form views (showPartNumber=true) also want the Part Number
                // code visible alongside its description - the List's own
                // widget usage deliberately leaves it off (options={'part_type': ...}
                // without 'show_part_number' - see job_hose_line_views.xml).
                label: this.props.showPartNumber ? `${p.part_number} - ${desc}` : desc,
            };
        });
        this.state.text = this._labelFromId(this.currentId) || this.state.text;
    }

    onInput(text) {
        this.state.text = text || "";
    }

    // Typing here never commits anything by itself (only an explicit pick
    // from the dropdown does, via onSelect) - any typed text left
    // unselected is discarded on blur, snapping the box back to whatever is
    // actually saved on the record.
    onBlurExtra() {
        this.state.text = this._labelFromId(this.currentId);
    }

    onSelect(opt) {
        this.state.text = opt.label;
        this.props.record.update({
            [this.props.name]: opt.id ? { id: opt.id, display_name: opt.label } : false,
        });
    }
}

export const pnmDisplayMany2oneField = {
    component: PnmDisplayMany2oneField,
    supportedTypes: ["many2one"],
    extractProps({ options }) {
        return { partType: options.part_type, showPartNumber: !!options.show_part_number };
    },
};

registry.category("fields").add("pnm_display_many2one", pnmDisplayMany2oneField);
