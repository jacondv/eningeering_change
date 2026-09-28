/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component } from "@odoo/owl";
import { HtmlField } from "@html_editor/fields/html_field";
import { Many2OneField } from "@web/views/fields/many2one/many2one_field";

// Renders the bulletin.bulletin.section One2many as a flowing document:
// each line becomes a full-width block with its Header on top, followed
// directly by whatever content widget its Section's content_type calls for
// - a Html editor for free-text sections, or an Approver picker + auto-shown
// signature/name/job title for Approval & Signature sections. The set of
// lines itself (which sections, in what order) comes entirely from the
// chosen Template - this widget only renders/edits the content of each,
// it does not add or remove lines.
export class BulletinSectionsField extends Component {
    static template = "bulletin.BulletinSectionsField";
    static components = { HtmlField, Many2OneField };
    static props = ["*"];

    get records() {
        return this.props.record.data[this.props.name].records;
    }
}

export const bulletinSectionsField = {
    component: BulletinSectionsField,
};

registry.category("fields").add("bulletin_sections", bulletinSectionsField);
