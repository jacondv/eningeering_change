/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class EngineeringChangeDashboard extends Component {
    static template = "engineering_change.Dashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ data: null });
        onWillStart(async () => {
            this.state.data = await this.orm.call("engineering.change", "get_dashboard_data", []);
        });
    }

    countOf(list, key) {
        const item = (list || []).find((i) => i.key === key);
        return item ? item.count : 0;
    }

    labelOf(list, key) {
        const item = (list || []).find((i) => i.key === key);
        return item ? item.label : key;
    }

    percentOf(count, total) {
        return total ? Math.round((count / total) * 100) : 0;
    }

    openRequests(domain, name) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name,
            res_model: "engineering.change",
            views: [
                [false, "list"],
                [false, "kanban"],
                [false, "form"],
            ],
            domain,
        });
    }

    async openTasksByState(stateKey) {
        await this.openTaskAction([["change_id", "!=", false], ["state", "=", stateKey]]);
    }

    async openOverdueTasks() {
        await this.openTaskAction([["change_id", "!=", false], ["is_overdue", "=", true]]);
    }

    async openTask(taskId) {
        await this.openTaskAction(null, taskId);
    }

    async openTaskAction(domain, resId) {
        // Server builds the action using this addon's own Task views (same
        // ones the Actions/Tasks menu uses), same idea as openRequests below
        // but project.task has several competing default views (core
        // Project, project_sms, project_todo...) so it can't just rely on
        // `[false, "list"/"form"]` picking ours like engineering.change does.
        const action = await this.orm.call("engineering.change", "get_ec_task_action", [], {
            domain,
            res_id: resId,
        });
        this.action.doAction(action);
    }

    openRecord(resModel, id) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: resModel,
            res_id: id,
            views: [[false, "form"]],
            target: "current",
        });
    }
}

registry.category("actions").add("engineering_change_dashboard", EngineeringChangeDashboard);
