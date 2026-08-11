/** @odoo-module **/

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

/**
 * "Suggest date" button for jacon.task.deadline.wizard.line rows.
 *
 * Deliberately does NOT go through a `type="object"` button (execute_action)
 * - that path saves/reloads the whole dialog and was closing the wizard
 * before the user could hit Save. Instead this fetches the suggestion with
 * a plain read-only RPC and applies it to the row via `record.update()`,
 * which only marks this field dirty in the browser - identical to typing
 * a new date in that cell by hand.
 */
class SuggestDeadlineButton extends Component {
    static template = "jacon_core.SuggestDeadlineButton";
    static props = { ...standardWidgetProps };

    setup() {
        this.orm = useService("orm");
    }

    async onClick() {
        const record = this.props.record;
        const suggested = await this.orm.call(
            record.resModel, "get_suggested_deadline", [record.resId]);
        if (suggested) {
            await record.update({ new_deadline: suggested });
        }
    }
}

registry.category("view_widgets").add("suggest_deadline_button", {
    component: SuggestDeadlineButton,
});
