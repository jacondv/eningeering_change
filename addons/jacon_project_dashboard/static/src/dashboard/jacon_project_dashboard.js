/** @odoo-module **/

import { Component, onMounted, onWillStart, onWillUnmount, useEffect, useRef, useState } from "@odoo/owl";
import { loadBundle } from "@web/core/assets";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const TASK_GANTT_VIEW_MODES = ["Day", "Week", "Month"];

// Remembers the Task Timeline's Day/Week/Month choice between visits,
// per browser - the panel's own date window is always the rolling
// previous/current/next month (server-side default in
// get_task_timeline), only the zoom level is a saved preference.
const TASK_GANTT_VIEW_MODE_STORAGE_KEY = "jacon_project_dashboard.task_gantt_view_mode";

function loadStoredTaskGanttViewMode() {
    try {
        const stored = localStorage.getItem(TASK_GANTT_VIEW_MODE_STORAGE_KEY);
        return TASK_GANTT_VIEW_MODES.includes(stored) ? stored : null;
    } catch {
        return null;
    }
}

function storeTaskGanttViewMode(mode) {
    try {
        localStorage.setItem(TASK_GANTT_VIEW_MODE_STORAGE_KEY, mode);
    } catch {
        // Storage unavailable (private mode, quota, ...) - silently skip.
    }
}

function _isoDate(d) {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${day}`;
}

/** Same as _isoDate, but rounds to the nearest midnight instead of
 * truncating - Frappe Gantt's "Day" view has no `snap_at` configured
 * (only Month/Year do), so a dragged bar's pixel X/width - and the
 * start/end dates on_date_change computes from them - are free-floating
 * fractions of a day, not snapped to whole-day columns as it might look
 * like on screen. Plain truncation of a fractional date always rounds
 * toward the earlier day, so both endpoints would drift a little short
 * on every drag, and each confirmed edit re-saves that shortened range
 * as the next drag's baseline - compounding into a visibly shrinking
 * task the more it gets moved. Shifting by 12h before truncating rounds
 * to the nearer day instead, for both start and end. */
function _isoDateRounded(d) {
    const shifted = new Date(d.getTime() + 12 * 60 * 60 * 1000);
    return _isoDate(shifted);
}

/** Calendar-day span between two 'YYYY-MM-DD' strings (end - start, so a
 * same-day task is 0). Parsed as local midnight, matching _isoDate. */
function _daySpan(startIso, endIso) {
    const start = new Date(`${startIso}T00:00:00`);
    const end = new Date(`${endIso}T00:00:00`);
    return Math.round((end - start) / (24 * 60 * 60 * 1000));
}

function _addDays(isoStr, days) {
    const d = new Date(`${isoStr}T00:00:00`);
    d.setDate(d.getDate() + days);
    return _isoDate(d);
}

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
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.mainViews = MAIN_VIEWS;
        this.taskGanttViewModes = TASK_GANTT_VIEW_MODES;
        this.canvasRefs = {
            main: useRef("chart_main"),
            plannedActual: useRef("chart_planned_actual"),
            topProjects: useRef("chart_top_projects"),
            overdueByProject: useRef("chart_overdue_by_project"),
        };
        this.taskGanttRef = useRef("task_gantt");
        this.taskGantt = null;
        // Frappe Gantt fires on_date_change on every mousemove while
        // dragging, not just on drop - so on_date_change only records the
        // latest position here, and the confirm popup opens once, on the
        // next mouseup (real drag end), from _onGanttMouseUp below.
        this._pendingGanttChange = null;
        this._onGanttMouseUp = () => {
            const change = this._pendingGanttChange;
            this._pendingGanttChange = null;
            if (change) {
                this.confirmTaskGanttChange(change);
            }
        };
        document.addEventListener("mouseup", this._onGanttMouseUp);
        onWillUnmount(() => document.removeEventListener("mouseup", this._onGanttMouseUp));
        this.charts = {};
        this.state = useState({
            loading: true,
            linesLoading: false,
            options: { projects: [], employees: [], task_types: [], years: [], months: [] },
            data: null,
            lines: [],
            taskGanttData: [],
            taskGanttViewMode: loadStoredTaskGanttViewMode() || "Day",
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

        // useEffect (not rAF/onMounted like the canvas charts below) -
        // runs after every DOM patch where taskGanttData actually changed,
        // including ones triggered from inside the confirm dialog after a
        // drag, where a plain rAF callback could fire before Owl finishes
        // re-mounting the (loading-toggled) container div.
        useEffect(
            () => this.renderTaskGantt(),
            () => [this.state.taskGanttData]
        );

        onWillStart(async () => {
            await Promise.all([
                loadBundle("web.chartjs_lib"),
                loadBundle("jacon_project_dashboard.frappe_gantt_lib"),
            ]);
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
        const [data, taskGanttData] = await Promise.all([
            this.orm.call("jacon.project.dashboard", "get_dashboard_data", [], { filters: this.state.filters }),
            this.fetchTaskTimeline(),
        ]);
        this.state.data = data;
        this.state.loading = false;
        // Assign AFTER loading flips back to false (not inside
        // fetchTaskTimeline, in parallel with the main fetch above) - the
        // Task Timeline's container div is unmounted while state.loading
        // is true (see the `t-if="state.loading"` in the template), so
        // assigning taskGanttData any earlier fires the render useEffect
        // while its ref is still null, silently no-op'ing renderTaskGantt.
        // Since taskGanttData then never changes again afterward, the
        // effect never re-fires and the chart stays empty until some
        // unrelated later action happens to reassign it. Setting it here,
        // in the same tick right after loading=false remounts the div,
        // guarantees the effect's post-patch run sees a live ref.
        this.state.taskGanttData = taskGanttData;
        requestAnimationFrame(() => {
            this.renderMainChart();
            if (this.state.showMore) {
                this.renderMoreCharts();
            }
        });
        await this.fetchLines();
    }

    /** Task Timeline is fetched separately from the rest of the dashboard
     * (its own fixed rolling previous/current/next month window,
     * independent of the Year/Months filter up top - see
     * get_task_timeline) - called from fetchData so Project/Engineer/Task
     * Type filter changes still reach it. Returns the data rather than
     * assigning it directly to state - see the ordering note in
     * fetchData for why the assignment itself has to happen later. */
    async fetchTaskTimeline() {
        return this.orm.call(
            "jacon.project.dashboard", "get_task_timeline", [], { filters: this.state.filters });
    }

    setTaskGanttViewMode(mode) {
        this.state.taskGanttViewMode = mode;
        storeTaskGanttViewMode(mode);
        if (this.taskGantt) {
            this.taskGantt.change_view_mode(mode);
        }
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

    // ------------------------------------------------------------
    // Task Timeline (Frappe Gantt, MIT-licensed, vendored locally under
    // static/lib - this Odoo install is Community, the native Gantt
    // view is Enterprise-only). Drag/resize a bar -> confirm popup ->
    // only written to the real task if the user confirms; declined or
    // dismissed snaps the bar back to where it was.
    // ------------------------------------------------------------
    renderTaskGantt() {
        const el = this.taskGanttRef.el;
        const rows = this.state.taskGanttData;
        if (!el || !window.Gantt) {
            return;
        }
        el.innerHTML = "";
        this.taskGantt = null;
        if (!rows || !rows.length) {
            return;
        }
        const tasks = rows.map((row) => ({
            id: String(row.id),
            name: `${row.employee}: ${row.name}`,
            start: row.start,
            end: row.end,
            progress: row.progress,
            // Red bar = this task didn't finish on time under the
            // priority queue (same flag as the Task form warning) - the
            // progress fill (green, via SCSS) stays a separate,
            // independent signal on top.
            custom_class: row.overloaded ? "o_pd_gantt_bar_overloaded" : "",
        }));
        this.taskGantt = new window.Gantt(el, tasks, {
            view_mode: this.state.taskGanttViewMode,
            scroll_to: "today",
            readonly_progress: true,
            // The date range is now explicit (the range picker above), so
            // there's no "infinite" axis to extend into - disabling this
            // also removes Frappe's own wheel listener that shifted the
            // date range on scroll, which is what made plain mouse-wheel
            // feel like it was jumping the chart around instead of just
            // scrolling the page/panel.
            infinite_padding: false,
            // Fires on every mousemove while dragging, not just on drop -
            // just record the latest position; _onGanttMouseUp (setup())
            // opens the confirm popup once, on the actual drag end.
            on_date_change: (task, start, end) => {
                this._pendingGanttChange = { ganttTaskId: task.id, taskId: parseInt(task.id, 10), start, end };
            },
            popup: (ctx) => this.taskGanttPopup(ctx),
        });
    }

/** Builds the whole popup body from scratch (task, project, assignee,
     * dates, allocated hours, progress, overdue) instead of relying on
     * Frappe's default popup, which only showed the bar's own overload
     * line - a manager clicking a task wants the same key facts they'd see
     * on the Task form without leaving the timeline. Overload/suggested
     * deadline stays a separate block appended only when relevant. Rebuilt
     * fully with set_details on every open (rather than appended to
     * get_details' content) so it can't accumulate duplicate lines across
     * repeated clicks on the same bar - the bug reported earlier. */
    taskGanttPopup({ task, set_details, add_action }) {
        const row = (this.state.taskGanttData || []).find((r) => String(r.id) === task.id);
        if (!row) {
            return;
        }
        const lines = [`<div class="o_pd_gantt_popup_info">`];
        if (row.project) {
            lines.push(`<div>Project: ${row.project}</div>`);
        }
        lines.push(`<div>Assignee: ${row.employee}</div>`);
        lines.push(`<div>${row.start} &rarr; ${row.end}</div>`);
        lines.push(`<div>Allocated: ${row.allocated_hours}h &middot; Progress: ${Math.round(row.progress)}%</div>`);
        if (row.overdue) {
            lines.push(`<div class="o_pd_gantt_popup_overdue">Overdue</div>`);
        }
        lines.push("</div>");
        if (row.overloaded) {
            lines.push(`<div class="o_pd_gantt_popup_overload">Over capacity by ${row.excess_hours}h`);
            if (row.suggested_deadline) {
                lines.push(`<br/>Suggested deadline: ${row.suggested_deadline} (no overload)`);
            }
            lines.push("</div>");
        }
        set_details(lines.join(""));
        if (row.overloaded && row.suggested_deadline) {
            add_action("Apply suggested deadline", () => this.applySuggestedDeadline(row));
        }
    }

    async applySuggestedDeadline(row) {
        await this.orm.write("project.task", [row.id], {
            date_deadline: `${row.suggested_deadline} 23:59:59`,
        });
        this.notification.add(
            `"${row.name}" deadline moved to ${row.suggested_deadline}.`, { type: "success" });
        await this.fetchData();
    }

    confirmTaskGanttChange({ ganttTaskId, taskId, start }) {
        const row = (this.state.taskGanttData || []).find((r) => r.id === taskId);
        if (!row) {
            return;
        }
        // Only the drop position's start date is trusted from the drag -
        // Frappe Gantt's "Day" view isn't snapped to whole-day columns
        // (see _isoDateRounded), so an independently-computed end from
        // the same imprecise geometry kept drifting the task's length
        // longer/shorter on every drag. Instead, the deadline always
        // keeps the task's original length (in calendar days) relative
        // to the new start - dragging only ever repositions the task,
        // it never resizes it.
        const newStartStr = _isoDateRounded(start);
        const originalSpanDays = _daySpan(row.start, row.end);
        const newEndStr = _addDays(newStartStr, originalSpanDays);
        const revert = () => this.taskGantt.update_task(ganttTaskId, { start: row.start, end: row.end });
        if (newStartStr === row.start) {
            return;
        }

        this.dialog.add(ConfirmationDialog, {
            title: "Move Task Dates?",
            body: `"${row.name}" (${row.employee}): ${row.start} → ${row.end} becomes ` +
                `${newStartStr} → ${newEndStr}. Apply this to the real task?`,
            confirm: async () => {
                await this.orm.write("project.task", [taskId], {
                    date_start: newStartStr,
                    date_deadline: `${newEndStr} 23:59:59`,
                });
                await this.fetchData();
            },
            cancel: revert,
            dismiss: revert,
        });
    }
}

registry.category("actions").add("jacon_project_dashboard", JaconProjectDashboard);
