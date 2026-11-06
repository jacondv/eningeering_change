/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useDebounced } from "@web/core/utils/timing";
import { deserializeDateTime, formatDateTime } from "@web/core/l10n/dates";

const CHECKSHEET_MODEL = "qc.checksheet";
const SEARCH_DEBOUNCE_MS = 300;
const JOB_STATUSES = [
    { key: "in_progress", label: "In Progress" },
    { key: "on_hold", label: "On Hold" },
    { key: "eol", label: "EOL" },
    { key: "cancelled", label: "Cancelled" },
];
const KPIS = [
    { key: "missing", label: "Jobs missing sheets" },
    { key: "waiting", label: "Waiting for approval" },
    { key: "draft", label: "Being written" },
    { key: "complete", label: "Jobs complete" },
];
const STATE_LABELS = { draft: "Draft", review: "In Review", released: "Released", superseded: "Superseded" };

/** Every Job against every Check Sheet Type. */
export class QcDashboard extends Component {
    static template = "qc_checksheet.Dashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.jobStatuses = JOB_STATUSES;
        this.kpiTiles = KPIS;
        this.state = useState({
            filters: { statuses: ["in_progress"], search: "", model_id: false, kpi: false, sort: "job", offset: 0 },
            data: null,
            loading: false,
        });
        this.reloadSoon = useDebounced(() => this.load(), SEARCH_DEBOUNCE_MS);
        onWillStart(() => this.load());
    }

    async load() {
        this.state.loading = true;
        try {
            this.state.data = await this.orm.call(CHECKSHEET_MODEL, "dashboard_data", [this.state.filters]);
        } finally {
            this.state.loading = false;
        }
    }

    get data() {
        return this.state.data;
    }

    setFilter(patch) {
        Object.assign(this.state.filters, patch, { offset: 0 });
        return this.load();
    }

    toggleStatus(key) {
        const statuses = new Set(this.state.filters.statuses);
        statuses.has(key) ? statuses.delete(key) : statuses.add(key);
        // At least one status, or there's nothing to show.
        return this.setFilter({ statuses: statuses.size ? [...statuses] : ["in_progress"] });
    }

    toggleKpi(key) {
        return this.setFilter({ kpi: this.state.filters.kpi === key ? false : key });
    }

    onSearchInput(ev) {
        this.state.filters.search = ev.target.value;
        this.state.filters.offset = 0;
        this.reloadSoon();
    }

    onModelChange(ev) {
        return this.setFilter({ model_id: parseInt(ev.target.value) || false });
    }

    sortBy(sort) {
        return this.setFilter({ sort });
    }

    page(step) {
        const { offset, page_size, total } = this.data;
        const next = offset + step * page_size;
        if (next >= 0 && next < total) {
            this.state.filters.offset = next;
            return this.load();
        }
    }

    get pagerLabel() {
        const { offset, page_size, total } = this.data;
        return total ? `${offset + 1}-${Math.min(offset + page_size, total)} of ${total}` : "0 Jobs";
    }

    // Cells

    stateLabel(state) {
        return STATE_LABELS[state] || state;
    }

    cellClass(cell) {
        return `o_qcd_cell o_qcd_cell_${cell.state}`;
    }

    isOverdue(cell) {
        return cell.waiting_days >= this.data.overdue_days;
    }

    cellTitle(cell) {
        if (!cell.id) {
            return cell.state === "missing" ? "Required for every Job, not created yet" : "";
        }
        const when = cell.updated_on ? formatDateTime(deserializeDateTime(cell.updated_on)) : "";
        const lines = [`Last change by ${cell.updated_by} on ${when}`];
        if (cell.reason) {
            lines.push(`Reason: ${cell.reason}`);
        }
        return lines.join("\n");
    }

    openSheet(id, layout) {
        if (layout === "standard") {
            return this.action.doAction({
                type: "ir.actions.client",
                tag: "qc_checksheet.editor",
                name: "Check Sheet",
                context: { active_id: id },
            });
        }
        return this.action.doAction({
            type: "ir.actions.act_window",
            res_model: CHECKSHEET_MODEL,
            res_id: id,
            views: [[false, "form"]],
        });
    }

    onCellClick(row, column) {
        const cell = row.cells[column.id];
        if (cell.id) {
            const target = cell.next || cell;
            return this.openSheet(target.id, cell.layout);
        }
        if (cell.state === "missing" && this.data.can_author) {
            return this.action.doAction({
                type: "ir.actions.client",
                tag: "qc_checksheet.editor",
                name: "New Check Sheet",
                context: { default_job_id: row.id, default_type_id: column.id },
            });
        }
    }

    openJob(row) {
        return this.action.doAction({
            type: "ir.actions.client",
            tag: "qc_checksheet.job",
            name: `QC: ${row.name}`,
            context: { active_id: row.id },
        });
    }

    newSheet() {
        return this.action.doAction("qc_checksheet.action_qc_checksheet_editor");
    }
}

registry.category("actions").add("qc_checksheet.dashboard", QcDashboard);
