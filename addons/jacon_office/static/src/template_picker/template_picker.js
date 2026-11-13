import { Component, onWillStart, useState } from "@odoo/owl";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

// Odoo's own file-type pictures, so nothing is downloaded or licensed separately.
const ICONS = {
    docx: "/web/static/img/mimetypes/document.svg",
    xlsx: "/web/static/img/mimetypes/spreadsheet.svg",
    pptx: "/web/static/img/mimetypes/presentation.svg",
};

/**
 * Drop-down to choose the template a new document starts from. Empty means a blank file.
 * Shows each template with the picture of its file type in front.
 */
export class JaconOfficeTemplatePicker extends Component {
    static template = "jacon_office.TemplatePicker";
    static components = { Dropdown, DropdownItem };
    static props = { ...standardFieldProps };

    setup() {
        this.orm = useService("orm");
        this.state = useState({ templates: [] });
        onWillStart(async () => {
            this.state.templates = await this.orm.searchRead(
                "jacon.office.template", [], ["name", "kind"], { order: "sequence, name" }
            );
        });
    }

    icon(kind) {
        return ICONS[kind] || ICONS.docx;
    }

    get selected() {
        const value = this.props.record.data[this.props.name];
        return value ? this.state.templates.find((t) => t.id === value.id) || null : null;
    }

    choose(template) {
        this.props.record.update({
            [this.props.name]: template ? { id: template.id, display_name: template.name } : false,
        });
    }
}

registry.category("fields").add("jacon_office_template_picker", {
    component: JaconOfficeTemplatePicker,
    supportedTypes: ["many2one"],
    displayName: "Office template picker",
});
