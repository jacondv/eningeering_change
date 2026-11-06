/** @odoo-module **/

import { Component, onWillStart, onWillUpdateProps, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { deserializeDate, formatDate } from "@web/core/l10n/dates";
import { Layout } from "@web/search/layout";
import { SearchBar } from "@web/search/search_bar/search_bar";
import { useSearchBarToggler } from "@web/search/search_bar/search_bar_toggler";

const MODEL = "qc.checksheet";

// Stands in for a list view's controller (see view_qc_checksheet_dashboard):
// the search bar's domain arrives as props.domain and every figure is reloaded
// from it. For Job Coverage and "Jobs missing sheets" only its conditions on the
// Job count (see _dashboard_job_domain).
export class QcDashboardController extends Component {
    static template = "qc_checksheet.Dashboard";
    static components = { Layout, SearchBar };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.searchBarToggler = useSearchBarToggler();
        this.state = useState({ data: null, modelSearch: "", jobSearch: "" });
        onWillStart(() => this.load(this.props.domain));
        onWillUpdateProps((nextProps) => this.load(nextProps.domain));
    }

    async load(domain) {
        // Only the latest search counts: an older reply arriving last is dropped.
        const request = (this.lastRequest = (this.lastRequest || 0) + 1);
        const data = await this.orm.call(MODEL, "get_dashboard_data", [domain]);
        if (request === this.lastRequest) {
            this.state.data = data;
        }
    }

    get kpis() {
        const { kpis, overdue_days, overdue_before } = this.state.data;
        return [
            { label: _t("Draft"), value: kpis.draft, css: "o_qcd_kpi_draft",
              domain: [["state", "=", "draft"]] },
            { label: _t("In Review"), value: kpis.review, css: "o_qcd_kpi_review",
              domain: [["state", "=", "review"]] },
            { label: _t("Waiting too long"), value: kpis.overdue, css: "o_qcd_kpi_overdue",
              hint: _t("In Review for %s days or more", overdue_days),
              domain: [["state", "=", "review"], ["submitted_date", "<=", overdue_before]] },
            { label: _t("Released"), value: kpis.released, css: "o_qcd_kpi_released",
              domain: [["state", "=", "released"]] },
        ];
    }

    get stateTotal() {
        return this.state.data.by_state.reduce((sum, item) => sum + item.count, 0);
    }

    /** The Models matching the box above the list. */
    /** The items whose label holds what was typed in the panel's own search box. */
    matching(items, term) {
        term = term.trim().toLowerCase();
        return term ? items.filter((item) => item.label.toLowerCase().includes(term)) : items;
    }

    /** Bars scaled to the biggest item, so the long tail stays readable. */
    maxOf(items) {
        return Math.max(0, ...items.map((item) => item.count));
    }

    get models() {
        return this.matching(this.state.data.by_model, this.state.modelSearch);
    }

    get jobs() {
        return this.matching(this.state.data.by_job, this.state.jobSearch);
    }

    openJob(item) {
        return this.action.doAction({
            type: "ir.actions.client",
            tag: "qc_checksheet.job",
            name: `QC: ${item.label}`,
            context: { active_id: item.key },
        });
    }

    percentOf(count, total) {
        return total ? Math.round((count / total) * 100) : 0;
    }

    formatDate(value) {
        return value ? formatDate(deserializeDate(value)) : "";
    }

    isOverdue(row) {
        return row.waiting_days >= this.state.data.overdue_days;
    }

    openSheets(domain, name) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name,
            res_model: MODEL,
            views: [[false, "list"], [false, "form"]],
            domain: [...this.props.domain, ["state", "!=", "superseded"], ...domain],
        });
    }

    async openMissingJobs() {
        this.action.doAction(await this.orm.call(MODEL, "action_open_missing_jobs", [this.props.domain]));
    }

    openSheet(row) {
        // Standard sheets are written on the editor page, Panel & Sticker ones on the form.
        if (row.layout === "standard") {
            return this.action.doAction({
                type: "ir.actions.client",
                tag: "qc_checksheet.editor",
                name: row.reference || row.name,
                context: { active_id: row.id },
            });
        }
        return this.action.doAction({
            type: "ir.actions.act_window",
            res_model: MODEL,
            res_id: row.id,
            views: [[false, "form"]],
        });
    }
}

registry.category("views").add("qc_checksheet_dashboard", {
    type: "list",
    Controller: QcDashboardController,
    // The dashboard has nothing to group.
    searchMenuTypes: ["filter", "favorite"],
});
