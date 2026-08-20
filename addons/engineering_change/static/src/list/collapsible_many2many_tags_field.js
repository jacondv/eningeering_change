import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { useState } from "@odoo/owl";
import {
    Many2ManyTagsField,
    many2ManyTagsField,
} from "@web/views/fields/many2many_tags/many2many_tags_field";

// List-view variant of the standard tags widget: when a record has more tags
// than `collapseLimit`, only the first few show - the rest collapse into a
// clickable "+N" tag (reusing TagsList's own tag.onClick hook) that expands
// the full list in place, instead of every tag wrapping the row taller and
// taller as the count grows.
export class CollapsibleMany2ManyTagsField extends Many2ManyTagsField {
    static props = {
        ...Many2ManyTagsField.props,
        collapseLimit: { type: Number, optional: true },
    };

    setup() {
        super.setup();
        this.collapseState = useState({ expanded: false });
    }

    get collapseLimit() {
        return this.props.collapseLimit || 3;
    }

    get tags() {
        const allTags = super.tags;
        if (allTags.length <= this.collapseLimit) {
            return allTags;
        }
        if (this.collapseState.expanded) {
            return [
                ...allTags,
                {
                    id: "__collapse_less__",
                    text: _t("Show less"),
                    canEdit: true,
                    onClick: (ev) => {
                        ev.stopPropagation();
                        this.collapseState.expanded = false;
                    },
                },
            ];
        }
        const hiddenCount = allTags.length - this.collapseLimit;
        return [
            ...allTags.slice(0, this.collapseLimit),
            {
                id: "__collapse_more__",
                text: `+${hiddenCount}`,
                canEdit: true,
                onClick: (ev) => {
                    ev.stopPropagation();
                    this.collapseState.expanded = true;
                },
            },
        ];
    }
}

export const collapsibleMany2ManyTagsField = {
    ...many2ManyTagsField,
    component: CollapsibleMany2ManyTagsField,
    extractProps(staticInfo, dynamicInfo) {
        const props = many2ManyTagsField.extractProps(staticInfo, dynamicInfo);
        props.collapseLimit = staticInfo.options.limit;
        return props;
    },
};

registry.category("fields").add("collapsible_many2many_tags", collapsibleMany2ManyTagsField);
