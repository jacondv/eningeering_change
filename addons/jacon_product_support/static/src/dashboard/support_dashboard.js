import { Component, onWillStart, onWillUpdateProps, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Layout } from "@web/search/layout";
import { SearchBar } from "@web/search/search_bar/search_bar";
import { useSearchBarToggler } from "@web/search/search_bar/search_bar_toggler";

const MODEL = "product.support.request";

// Stands in for a list view's controller (see view_product_support_request_dashboard):
// the search bar's domain arrives as props.domain and every figure is reloaded from it.
export class SupportDashboardController extends Component {
    static template = "jacon_product_support.Dashboard";
    static components = { Layout, SearchBar };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.searchBarToggler = useSearchBarToggler();
        this.state = useState({ data: null });
        onWillStart(() => this.load(this.props.domain));
        onWillUpdateProps((nextProps) => this.load(nextProps.domain));
    }

    async load(domain) {
        this.state.data = await this.orm.call(MODEL, "get_dashboard_data", [domain]);
    }

    get kpis() {
        const { kpis } = this.state.data;
        return [
            { label: _t("Open"), value: kpis.open, css: "o_ps_kpi_open",
              domain: [["state", "=", "draft"]] },
            { label: _t("Machine Down"), value: kpis.down, css: "o_ps_kpi_down",
              domain: [["state", "=", "draft"], ["machine_status", "=", "down"]] },
            { label: _t("Resolved (to close)"), value: kpis.resolved, css: "o_ps_kpi_resolved",
              domain: [["state", "=", "resolved"]] },
            { label: _t("Closed this month"), value: kpis.closed_month, css: "o_ps_kpi_closed",
              domain: [["state", "=", "closed"], ["closed_date", ">=", this.monthStart]] },
        ];
    }

    get panels() {
        const { data } = this.state;
        return [
            { title: _t("By Stage"), field: "state", items: data.by_state },
            { title: _t("By Fault Category"), field: "fault_category_id", items: data.by_category },
            { title: _t("By Model"), field: "model_id", items: data.by_model },
            { title: _t("By Customer"), field: "partner_id", items: data.by_customer },
        ];
    }

    get monthStart() {
        const now = new Date();
        return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-01`;
    }

    percentOf(count) {
        return this.state.data.total ? Math.round((count / this.state.data.total) * 100) : 0;
    }

    openRequests(domain, name) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name,
            res_model: MODEL,
            views: [[false, "list"], [false, "kanban"], [false, "form"]],
            domain: [...this.props.domain, ...domain],
        });
    }

    openRecord(id) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: MODEL,
            res_id: id,
            views: [[false, "form"]],
        });
    }
}

registry.category("views").add("product_support_dashboard", {
    type: "list",
    Controller: SupportDashboardController,
});
