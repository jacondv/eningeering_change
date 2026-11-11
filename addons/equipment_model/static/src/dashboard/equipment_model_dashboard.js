import { Component, onWillStart, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";

// Counts of Groups, Product Families, Models and Jobs
// (equipment.model.get_dashboard_data). Every figure opens the list it counts.
// Clicking a Group narrows the Product Family table down to it.
export class EquipmentModelDashboard extends Component {
    static template = "equipment_model.Dashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ data: null, groupId: null, isManager: false });
        onWillStart(async () => {
            [this.state.data, this.state.isManager] = await Promise.all([
                this.orm.call("equipment.model", "get_dashboard_data", []),
                user.hasGroup("equipment_model.group_equipment_model_manager"),
            ]);
        });
    }

    get families() {
        const { families } = this.state.data;
        return this.state.groupId ? families.filter((family) => family.group_id === this.state.groupId) : families;
    }

    get selectedGroup() {
        return this.state.data.groups.find((group) => group.id === this.state.groupId);
    }

    get maxJobs() {
        return Math.max(1, ...this.state.data.groups.map((group) => group.jobs));
    }

    barWidth(jobs) {
        return `${Math.round((jobs / this.maxJobs) * 100)}%`;
    }

    toggleGroup(groupId) {
        this.state.groupId = this.state.groupId === groupId ? null : groupId;
    }

    open(resModel, name, domain = []) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name,
            res_model: resModel,
            views: [
                [false, "list"],
                [false, "form"],
            ],
            domain,
        });
    }

    openGroups() {
        this.open("equipment.model.category", _t("Groups"));
    }

    openFamilies(group) {
        this.open("equipment.model.family", group ? group.name : _t("Product Families"),
            group ? [["category_id", "=", group.id]] : []);
    }

    openModels(name, domain) {
        this.open("equipment.model", name, domain);
    }

    openJobs(name, domain) {
        this.open("project.project", name, [...this.state.data.job_domain, ...domain]);
    }

    openGroupRecord(group) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "equipment.model.category",
            res_id: group.id,
            views: [[false, "form"]],
        });
    }

    async importFile() {
        await this.action.doAction("equipment_model.action_equipment_model_import", {
            onClose: () => this.reload(),
        });
    }

    async exportFile() {
        await this.action.doAction("equipment_model.action_equipment_model_export");
    }

    async reload() {
        this.state.data = await this.orm.call("equipment.model", "get_dashboard_data", []);
    }
}

registry.category("actions").add("equipment_model_dashboard", EquipmentModelDashboard);
