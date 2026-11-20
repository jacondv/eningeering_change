import { Component, onWillUnmount, useEffect, useRef, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { X2ManyField, x2ManyField } from "@web/views/fields/x2many/x2many_field";
import { ListRenderer } from "@web/views/list/list_renderer";

const CHECK_MODEL = "engineering.change.action.check";

/** The lines that are picked. (An embedded list's own `selection` is always empty: Odoo has no picking there.) */
const pickedOf = (list) => list.records.filter((record) => record.selected);

/**
 * The list of the Impact Checklist, with check boxes. What Odoo does not give an embedded list:
 *   - `list.selection` is always empty, and the header check box calls list.toggleSelection(), which only
 *     the full-page lists have (it fails here): the header box is "check all / uncheck all" below, and it is
 *     checked exactly when every line is;
 *   - the picks are made through the model's queue, and nothing tells the list or the field: once they are
 *     in, the list draws itself again (so the header box follows the lines) and the field is told.
 */
class EcCheckListRenderer extends ListRenderer {
    static props = [...ListRenderer.props, "onSelectionChange?"];

    get selectAll() {
        const records = this.props.list.records;
        return records.length > 0 && pickedOf(this.props.list).length === records.length;
    }

    toggleSelection() {
        if (!this.canSelectRecord) {
            return;
        }
        const list = this.props.list;
        const everyoneIsPicked = this.selectAll;
        for (const record of list.records) {
            record.toggleSelection(!everyoneIsPicked);
        }
        this.selectionChanged();
    }

    toggleRecordSelection(record, ev) {
        if (!this.canSelectRecord) {
            return;
        }
        record.toggleSelection();
        this.selectionChanged();
    }

    setup() {
        super.setup();
        onWillUnmount(() => clearTimeout(this.selectionTimer)); // nothing is drawn on a list that is gone
    }

    selectionChanged() {
        clearTimeout(this.selectionTimer);
        this.selectionTimer = setTimeout(() => {
            this.render(true);
            this.props.onSelectionChange?.();
        });
    }
}

/**
 * The Impact Checklist of an action (one line per Impacted Model / Job Number): the embedded list with a
 * check box on every line (and one in the header to pick them all), and, once some lines are picked, a bar
 * to set their status in one go: "3 selected   [To do] [Done] [No change]".
 */
export class EcCheckListField extends X2ManyField {
    static template = "engineering_change.EcCheckListField";
    static components = { ...X2ManyField.components, ListRenderer: EcCheckListRenderer };

    setup() {
        super.setup();
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.busy = useState({ value: false });
        this.picked = useState({ count: 0 });
    }

    // Odoo draws no check boxes in an embedded list unless asked to.
    get rendererProps() {
        return {
            ...super.rendererProps,
            allowSelectors: true,
            onSelectionChange: () => this.refreshPicked(),
        };
    }

    refreshPicked() {
        this.picked.count = pickedOf(this.list).length;
    }

    get selectedIds() {
        return pickedOf(this.list)
            .map((record) => record.resId)
            .filter(Boolean);
    }

    get selectedCount() {
        return this.picked.count;
    }

    /** "3/9": the lines done or found to need no change, out of all of them (as the lines are now). */
    get progressText() {
        const lines = this.list.records;
        const resolved = lines.filter((line) => line.data.status !== "todo").length;
        return `${resolved}/${lines.length}`;
    }

    async setStatus(status) {
        const ids = this.selectedIds;
        if (!ids.length || this.busy.value) {
            return;
        }
        this.busy.value = true;
        try {
            // What was typed in the form is saved first: the lines are read again afterwards.
            if ((await this.props.record.save()) === false) {
                return;
            }
            const result = await this.orm.call(CHECK_MODEL, "action_set_status", [ids, status]);
            await this.props.record.load();
            this.refreshPicked(); // the lines are new records: nothing is picked any more
            if (result.skipped) {
                this.notification.add(
                    _t("%s line(s) were left as they were: you may not change them.", result.skipped),
                    { type: "warning" }
                );
            }
        } finally {
            this.busy.value = false;
        }
    }
}

registry.category("fields").add("ec_check_list", { ...x2ManyField, component: EcCheckListField });

/**
 * Writes the progress of the Impact Checklist on its tab: "Impact Checklist (3/8)", in red while a line is
 * still to do. A tab's title is fixed text in Odoo, so this small field (kept out of sight, outside the
 * tabs, so that it is there whichever tab is open) puts the numbers on the tab as data attributes that the
 * style sheet shows.
 */
export class EcCheckTabField extends Component {
    static template = "engineering_change.EcCheckTabField";
    static props = { ...standardFieldProps };

    setup() {
        this.root = useRef("root");
        useEffect(() => this.mark());
    }

    mark() {
        const form = this.root.el?.closest(".o_form_view, .o_form_renderer");
        const tab = form?.querySelector('a.nav-link[name="ec_checks"]');
        if (!tab) {
            return;
        }
        const lines = this.props.record.data.ec_check_ids?.records || [];
        const resolved = lines.filter((line) => line.data.status !== "todo").length;
        if (!lines.length) {
            delete tab.dataset.ecProgress;
            delete tab.dataset.ecTodo;
            return;
        }
        tab.dataset.ecProgress = `${resolved}/${lines.length}`;
        tab.dataset.ecTodo = resolved < lines.length ? "1" : "0";
    }
}

registry.category("fields").add("ec_check_tab", {
    component: EcCheckTabField,
    displayName: _t("Impact Checklist tab"),
    supportedTypes: ["char"],
});
