/** @odoo-module **/

import { Component, onWillStart, useRef, useState } from "@odoo/owl";
import { loadBundle } from "@web/core/assets";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

function todayISO() {
    return new Date().toISOString().slice(0, 10);
}

function startOfYearISO() {
    return `${new Date().getFullYear()}-01-01`;
}

const CHART_COLORS = [
    "#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f",
    "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac",
];

export class JaconProjectDashboard extends Component {
    static template = "jacon_project_dashboard.Dashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.canvasRefs = {
            plannedActual: useRef("chart_planned_actual"),
            byMonth: useRef("chart_by_month"),
            byMonthTaskType: useRef("chart_by_month_task_type"),
            byTaskType: useRef("chart_by_task_type"),
            byEmployee: useRef("chart_by_employee"),
            topProjects: useRef("chart_top_projects"),
            overdueByProject: useRef("chart_overdue_by_project"),
        };
        this.charts = {};
        this.state = useState({
            loading: true,
            options: { projects: [], employees: [], task_types: [] },
            data: null,
            filters: {
                date_from: startOfYearISO(),
                date_to: todayISO(),
                project_ids: [],
                employee_ids: [],
                task_types: [],
            },
        });

        onWillStart(async () => {
            await loadBundle("web.chartjs_lib");
            this.state.options = await this.orm.call("jacon.project.dashboard", "get_filter_options", []);
            await this.fetchData();
        });
    }

    async fetchData() {
        this.state.loading = true;
        this.state.data = await this.orm.call(
            "jacon.project.dashboard", "get_dashboard_data", [], { filters: this.state.filters });
        this.state.loading = false;
        // Charts render into <canvas> elements that only exist once `data`
        // is truthy, so defer until after the next render pass.
        requestAnimationFrame(() => this.renderCharts());
    }

    onDateChange(field, ev) {
        this.state.filters[field] = ev.target.value;
        this.fetchData();
    }

    toggleFilterValue(field, value) {
        const current = this.state.filters[field];
        const idx = current.indexOf(value);
        if (idx === -1) {
            current.push(value);
        } else {
            current.splice(idx, 1);
        }
        this.fetchData();
    }

    isFilterActive(field, value) {
        return this.state.filters[field].includes(value);
    }

    clearFilter(field) {
        this.state.filters[field] = [];
        this.fetchData();
    }

    // ------------------------------------------------------------
    // Chart rendering
    // ------------------------------------------------------------
    _renderChart(key, config) {
        const canvas = this.canvasRefs[key].el;
        if (!canvas) {
            return;
        }
        if (this.charts[key]) {
            this.charts[key].destroy();
        }
        this.charts[key] = new Chart(canvas, config);
    }

    renderCharts() {
        const data = this.state.data;
        if (!data) {
            return;
        }

        this._renderChart("plannedActual", {
            type: "bar",
            data: {
                labels: data.planned_vs_actual_by_project.map((r) => r.name),
                datasets: [
                    {
                        label: "Planned",
                        data: data.planned_vs_actual_by_project.map((r) => r.planned),
                        backgroundColor: "#59a14f",
                    },
                    {
                        label: "Spent",
                        data: data.planned_vs_actual_by_project.map((r) => r.spent),
                        backgroundColor: data.planned_vs_actual_by_project.map(
                            (r) => (r.over_budget ? "#e15759" : "#4e79a7")),
                    },
                ],
            },
            options: { responsive: true, maintainAspectRatio: false },
        });

        this._renderChart("byMonth", {
            type: "line",
            data: {
                labels: data.by_month.map((r) => r.month),
                datasets: [{
                    label: "Spent Hours",
                    data: data.by_month.map((r) => r.spent_hours),
                    borderColor: "#4e79a7",
                    backgroundColor: "#4e79a733",
                    fill: true,
                    tension: 0.2,
                }],
            },
            options: { responsive: true, maintainAspectRatio: false },
        });

        const months = [...new Set(data.by_month_task_type.map((r) => r.month))];
        const taskTypes = [...new Set(data.by_month_task_type.map((r) => r.task_type))];
        this._renderChart("byMonthTaskType", {
            type: "bar",
            data: {
                labels: months,
                datasets: taskTypes.map((tt, i) => ({
                    label: tt,
                    data: months.map((m) => {
                        const row = data.by_month_task_type.find((r) => r.month === m && r.task_type === tt);
                        return row ? row.hours : 0;
                    }),
                    backgroundColor: CHART_COLORS[i % CHART_COLORS.length],
                })),
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                scales: { x: { stacked: true }, y: { stacked: true } },
            },
        });

        this._renderChart("byTaskType", {
            type: "bar",
            data: {
                labels: data.by_task_type.map((r) => r.label),
                datasets: [{
                    label: "Spent Hours",
                    data: data.by_task_type.map((r) => r.spent_hours),
                    backgroundColor: CHART_COLORS,
                }],
            },
            options: { responsive: true, maintainAspectRatio: false, indexAxis: "y" },
        });

        this._renderChart("byEmployee", {
            type: "bar",
            data: {
                labels: data.by_employee.map((r) => r.name),
                datasets: [{
                    label: "Spent Hours",
                    data: data.by_employee.map((r) => r.spent_hours),
                    backgroundColor: "#f28e2b",
                }],
            },
            options: { responsive: true, maintainAspectRatio: false, indexAxis: "y" },
        });

        this._renderChart("topProjects", {
            type: "bar",
            data: {
                labels: data.top_projects.map((r) => r.name),
                datasets: [{
                    label: "Spent Hours",
                    data: data.top_projects.map((r) => r.spent_hours),
                    backgroundColor: "#76b7b2",
                }],
            },
            options: { responsive: true, maintainAspectRatio: false, indexAxis: "y" },
        });

        this._renderChart("overdueByProject", {
            type: "bar",
            data: {
                labels: data.overdue_by_project.map((r) => r.name),
                datasets: [{
                    label: "Overdue Tasks",
                    data: data.overdue_by_project.map((r) => r.overdue_count),
                    backgroundColor: "#e15759",
                }],
            },
            options: { responsive: true, maintainAspectRatio: false, indexAxis: "y" },
        });
    }

    // ------------------------------------------------------------
    // Heatmap helpers
    // ------------------------------------------------------------
    get heatmapEmployees() {
        return [...new Set(this.state.data.employee_task_type_matrix.map((r) => r.employee))];
    }

    get heatmapTaskTypes() {
        return [...new Set(this.state.data.employee_task_type_matrix.map((r) => r.task_type))];
    }

    heatmapValue(employee, taskType) {
        const row = this.state.data.employee_task_type_matrix.find(
            (r) => r.employee === employee && r.task_type === taskType);
        return row ? row.hours : 0;
    }

    get heatmapMax() {
        return Math.max(1, ...this.state.data.employee_task_type_matrix.map((r) => r.hours));
    }

    heatmapStyle(value) {
        const intensity = Math.min(1, value / this.heatmapMax);
        return `background-color: rgba(78, 121, 167, ${intensity.toFixed(2)});` +
            (intensity > 0.55 ? " color: #fff;" : "");
    }
}

registry.category("actions").add("jacon_project_dashboard", JaconProjectDashboard);
