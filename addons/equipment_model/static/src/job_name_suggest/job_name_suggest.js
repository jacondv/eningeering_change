import { Component } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

// "Suggest" next to a Project's name: fills in <Product Family>-<next number>
// (project.project.get_suggested_job_name) without saving, so it can still be
// edited. Not a server button, which would save the Project first.
export class JobNameSuggest extends Component {
    static template = "equipment_model.JobNameSuggest";
    static props = { ...standardWidgetProps };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
    }

    get visible() {
        const { data } = this.props.record;
        // jacon_core's edit lock keeps an existing Project read-only until unlocked.
        const locked = "is_unlocked" in data && !data.is_unlocked;
        return !this.props.readonly && !locked;
    }

    async suggest() {
        const model = this.props.record.data.model_id;
        const modelId = model && (model.id ?? model[0]);
        if (!modelId) {
            this.notification.add(_t("Choose a Model first: the name comes from its Product Family."), {
                type: "warning",
            });
            return;
        }
        const name = await this.orm.call("project.project", "get_suggested_job_name", [modelId]);
        await this.props.record.update({ name });
    }
}

registry.category("view_widgets").add("job_name_suggest", {
    component: JobNameSuggest,
});
