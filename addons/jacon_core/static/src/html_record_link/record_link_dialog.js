import { Component, useState } from "@odoo/owl";
import { AutoComplete } from "@web/core/autocomplete/autocomplete";
import { Dialog } from "@web/core/dialog/dialog";
import { Domain } from "@web/core/domain";
import { _t } from "@web/core/l10n/translation";
import { RecordSelector } from "@web/core/record_selectors/record_selector";
import { registry } from "@web/core/registry";
import { useChildRef, useService } from "@web/core/utils/hooks";

const SEARCH_LIMIT = 8;

// What a record can be linked to is registered by whichever addon owns its
// model, so that this one doesn't have to depend on all of them:
//
//     recordLinkTypes.add("my_type", {
//         label: "My Type",            // shown on the type's button
//         prefix: "MT",                // starts the link's text
//         resModel: "my.model",
//         actionPath: "my-action",     // an action's `path`, opens /odoo/<actionPath>/<id>
//         titleField: "title",
//         numberField: "name",         // optional, a reference shown before the title
//         unassignedNumber: "New",     // optional, its value before a number is assigned
//         domain: [],                  // optional, leaves records out of the search
//         filter: {                    // optional, narrows the search down by a many2one,
//             field: "partner_id",     // whose value also tells same-named links apart
//             resModel: "res.partner",
//             label: "Customer",
//             placeholder: "All customers",
//             domain: [],              // optional, leaves records out of the filter's choices
//         },
//     }, { sequence: 10 });            // the button's position
export const recordLinkTypes = registry.category("jacon_core.record_link_types");

export class RecordLinkDialog extends Component {
    static template = "jacon_core.RecordLinkDialog";
    static components = { AutoComplete, Dialog, RecordSelector };
    static props = {
        close: Function,
        onSelect: Function, // (url, text) => void
    };

    setup() {
        this.orm = useService("orm");
        this.types = recordLinkTypes.getAll();
        this.state = useState({ typeIndex: 0, filterId: false });
        this.searchInput = useChildRef();
        this.sources = [{ options: (query) => this.loadOptions(query) }];
    }

    get title() {
        return _t("Link to Record");
    }

    get currentType() {
        return this.types[this.state.typeIndex];
    }

    selectType(index) {
        this.state.typeIndex = index;
        this.state.filterId = false;
    }

    selectFilter(id) {
        this.state.filterId = id;
        this.searchInput.el.focus();
    }

    async loadOptions(query) {
        const type = this.currentType;
        const filterField = type.filter?.field;
        const searchFields = [type.numberField, type.titleField].filter(Boolean);
        const records = await this.orm.searchRead(
            type.resModel,
            Domain.and([
                type.domain || [],
                Domain.or(searchFields.map((field) => [[field, "ilike", query.trim()]])),
                this.state.filterId ? [[filterField, "=", this.state.filterId]] : [],
            ]).toList(),
            [...searchFields, ...(filterField ? [filterField] : [])],
            { limit: SEARCH_LIMIT }
        );
        if (!records.length) {
            return [{ label: _t("(no result)") }];
        }
        return records.map((record) => {
            const text = this.linkText(type, record);
            return { label: text, onSelect: () => this.select(type, record, text) };
        });
    }

    linkText(type, record) {
        const number = record[type.numberField];
        const title = record[type.titleField];
        const filterValue = record[type.filter?.field];
        const text = number && number !== type.unassignedNumber
            ? `${type.prefix} ${number} - ${title}`
            : `${type.prefix} - ${title}`;
        return filterValue ? `${text} (${filterValue[1]})` : text;
    }

    select(type, record, text) {
        this.props.onSelect(`/odoo/${type.actionPath}/${record.id}`, text);
        this.props.close();
    }
}
