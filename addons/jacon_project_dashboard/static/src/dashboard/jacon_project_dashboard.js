/** @odoo-module **/

import { Component, onMounted, onWillStart, useRef, useState } from "@odoo/owl";
import { loadBundle } from "@web/core/assets";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const CHART_COLORS = [
    "#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f",
    "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac",
];

const MAIN_VIEWS = [
    { key: "month", label: "Hour by Month" },
    { key: "employee", label: "Hour by Engineer" },
    { key: "task_type", label: "Hour by Task Type" },
];

// Remembers the filter bar (Year/Month/Project/Engineer/Task Type)
// between visits, per browser - until the user explicitly changes it or
// clicks "Reset filters". Not synced across users/devices on purpose,
// same as any other client-side UI preference.
const FILTERS_STORAGE_KEY = "jacon_project_dashboard.filters";

function loadStoredFilters() {
    try {
        const raw = localStorage.getItem(FILTERS_STORAGE_KEY);
        return raw ? JSON.parse(raw) : null;
    } catch {
        return null;
    }
}

function storeFilters(filters) {
    try {
        localStorage.setItem(FILTERS_STORAGE_KEY, JSON.stringify(filters));
    } catch {
        // Storage unavailable (private mode, quota, ...) - silently skip,
        // filters just won't persist for this session.
    }
}

export class JaconProjectDashboard extends Component {
    static template = "jacon_project_dashboard.Dashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.mainViews = MAIN_VIEWS;
        this.canvasRefs = {
            main: useRef("chart_main"),
            plannedActual: useRef("chart_planned_actual"),
            topProjects: useRef("chart_top_projects"),
            overdueByProject: useRef("chart_overdue_by_project"),
        };
        this.charts = {};
        this.state = useState({
            loading: true,
            linesLoading: false,
            options: { projects: [], employees: [], task_types: [], years: [], months: [] },
            data: null,
            lines: [],
            filters: {
                years: [new Date().getFullYear()],
                months: [],
                project_ids: [],
                employee_ids: [],
                task_types: [],
            },
            mainView: "month",
            chartType: "bar",
            stacked: false,
            drill: { employee_id: null, task_type: null, month: null, year: null },
            showMore: false,
        });

        onWillStart(async () => {
            await loadBundle("web.chartjs_lib");
            this.state.options = await this.orm.call("jacon.project.dashboard", "get_filter_options", []);
            const stored = loadStoredFilters();
            if (stored) {
                Object.assign(this.state.filters, stored);
            } else if (this.state.options.current_year) {
                this.state.filters.years = [this.state.options.current_year];
            }
            await this.fetchData();
        });

        // fetchData's own render (below) runs inside onWillStart on first
        // load, i.e. before Owl has mounted the canvases for the first
        // time - `requestAnimationFrame` isn't a reliable enough guard for
        // that first paint, so re-render once mounting is guaranteed done.
        // Subsequent filter/tab changes call fetchData after mount, where
        // the rAF render already works fine.
        onMounted(() => {
            if (this.state.data) {
                this.renderMainChart();
                if (this.state.showMore) {
                    this.renderMoreCharts();
                }
            }
        });
    }

    // ------------------------------------------------------------
    // Filters
    // ------------------------------------------------------------
    async fetchData() {
        storeFilters(this.state.filters);
        this.state.loading = true;
        this.state.data = await this.orm.call(
            "jacon.project.dashboard", "get_dashboard_data", [], { filters: this.state.filters });
        this.state.loading = false;
        requestAnimationFrame(() => {
            this.renderMainChart();
            if (this.state.showMore) {
                this.renderMoreCharts();
            }
        });
        await this.fetchLines();
    }

    async fetchLines() {
        this.state.linesLoading = true;
        this.state.lines = await this.orm.call(
            "jacon.project.dashboard", "get_timesheet_lines", [],
            { filters: this.state.filters, drill: this.state.drill });
        this.state.linesLoading = false;
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

    /** Backing values for the "All" shortcut of each multi-select filter -
     * kept in one place so the template doesn't need to know the shape of
     * each options list (ids vs keys vs plain numbers). */
    allFilterValues(field) {
        switch (field) {
            case "years": return this.state.options.years;
            case "months": return this.state.options.months.map((m) => m.key);
            case "project_ids": return this.state.options.projects.map((p) => p.id);
            case "employee_ids": return this.state.options.employees.map((e) => e.id);
            case "task_types": return this.state.options.task_types.map((t) => t.key);
            default: return [];
        }
    }

    selectAllFilter(field) {
        this.state.filters[field] = [...this.allFilterValues(field)];
        this.fetchData();
    }

    isAllSelected(field) {
        return this.state.filters[field].length === this.allFilterValues(field).length;
    }

    resetAllFilters() {
        this.state.filters = {
            years: this.state.options.current_year ? [this.state.options.current_year] : [new Date().getFullYear()],
            months: [],
            project_ids: [],
            employee_ids: [],
            task_types: [],
        };
        this.state.drill = { employee_id: null, task_type: null, month: null, year: null };
        this.fetchData();
    }

    // ------------------------------------------------------------
    // Main chart (Month / Engineer / Task Type - one canvas, switched by tab)
    // ------------------------------------------------------------
    setMainView(view) {
        this.state.mainView = view;
        this.state.stacked = false;
        requestAnimationFrame(() => this.renderMainChart());
    }

    setChartType(type) {
        this.state.chartType = type;
        requestAnimationFrame(() => this.renderMainChart());
    }

    toggleStacked() {
        this.state.stacked = !this.state.stacked;
        requestAnimationFrame(() => this.renderMainChart());
    }

    setDrill(patch) {
        this.state.drill = { employee_id: null, task_type: null, month: null, year: null, ...patch };
        this.fetchLines();
    }

    /** 'YYYY-MM' chart label -> {year, month} drill patch. */
    _monthDrillFromLabel(label) {
        const [y, m] = (label || "").split("-");
        return { year: y ? parseInt(y, 10) : null, month: m ? parseInt(m, 10) : null };
    }

    clearDrill() {
        this.state.drill = { employee_id: null, task_type: null, month: null, year: null };
        this.fetchLines();
    }

    get hasDrill() {
        const d = this.state.drill;
        return !!(d.employee_id || d.task_type || d.month);
    }

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

    renderMainChart() {
        const data = this.state.data;
        if (!data) {
            return;
        }
        if (this.state.mainView === "month") {
            this._renderMonthChart(data);
        } else if (this.state.mainView === "employee") {
            this._renderEmployeeChart(data);
        } else {
            this._renderTaskTypeChart(data);
        }
    }

    _renderMonthChart(data) {
        if (this.state.stacked) {
            const months = [...new Set(data.by_month_task_type.map((r) => r.month))];
            const taskTypes = [...new Set(data.by_month_task_type.map((r) => r.task_type))];
            this._renderChart("main", {
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
                    onClick: (ev, elements) => {
                        if (elements.length) {
                            this.setDrill(this._monthDrillFromLabel(months[elements[0].index]));
                        }
                    },
                },
            });
            return;
        }
        this._renderChart("main", {
            type: this.state.chartType,
            data: {
                labels: data.by_month.map((r) => r.month),
                datasets: [{
                    label: "Spent Hours",
                    data: data.by_month.map((r) => r.spent_hours),
                    borderColor: "#4e79a7",
                    backgroundColor: this.state.chartType === "line" ? "#4e79a733" : "#4e79a7",
                    fill: this.state.chartType === "line",
                    tension: 0.25,
                }],
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                onClick: (ev, elements) => {
                    if (elements.length) {
                        this.setDrill(this._monthDrillFromLabel(data.by_month[elements[0].index].month));
                    }
                },
            },
        });
    }

    _renderEmployeeChart(data) {
        this._renderChart("main", {
            type: "bar",
            data: {
                labels: data.by_employee.map((r) => r.name),
                datasets: [{
                    label: "Spent Hours",
                    data: data.by_employee.map((r) => r.spent_hours),
                    backgroundColor: "#f28e2b",
                }],
            },
            options: {
                responsive: true, maintainAspectRatio: false, indexAxis: "y",
                onClick: (ev, elements) => {
                    if (elements.length) {
                        this.setDrill({ employee_id: data.by_employee[elements[0].index].id });
                    }
                },
            },
        });
    }

    _renderTaskTypeChart(data) {
        this._renderChart("main", {
            type: "bar",
            data: {
                labels: data.by_task_type.map((r) => r.label),
                datasets: [{
                    label: "Spent Hours",
                    data: data.by_task_type.map((r) => r.spent_hours),
                    backgroundColor: CHART_COLORS,
                }],
            },
            options: {
                responsive: true, maintainAspectRatio: false, indexAxis: "y",
                onClick: (ev, elements) => {
                    if (elements.length) {
                        this.setDrill({ task_type: data.by_task_type[elements[0].index].key });
                    }
                },
            },
        });
    }

    // ------------------------------------------------------------
    // More insights (accordion, rendered on demand - canvases inside a
    // collapsed panel have no size until it's opened)
    // ------------------------------------------------------------
    toggleShowMore() {
        this.state.showMore = !this.state.showMore;
        if (this.state.showMore) {
            requestAnimationFrame(() => this.renderMoreCharts());
        }
    }

    renderMoreCharts() {
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

    // ------------------------------------------------------------
    // Capacity panel helpers
    // ------------------------------------------------------------
    capacityBarStyle(row) {
        const pct = Math.max(0, Math.min(100, row.allocated ? (row.spent / row.allocated) * 100 : 100));
        return `width: ${pct}%;`;
    }

    capacityLevel(row) {
        if (row.free_pct < 0) {
            return "o_pd_capacity_over";
        }
        if (row.free_pct < 15) {
            return "o_pd_capacity_tight";
        }
        return "o_pd_capacity_free";
    }
}

registry.category("actions").add("jacon_project_dashboard", JaconProjectDashboard);
