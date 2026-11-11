import { Component, onWillStart, useRef, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";

const JOB_LIMIT = 100;
const MATCHING_JOBS_LIMIT = 2000;
// Id 0 stands for "no Product Family" (see equipment.model.get_dashboard_data).
const NO_FAMILY = 0;

const contains = (value, text) => (value || "").toLowerCase().includes(text.toLowerCase());

// Three columns, Group > Product Family > Model, each narrowed by what is picked
// in the one before; the Jobs of whatever is picked or searched are listed below.
//
// Picking a row and searching both end up as facets above the columns: a facet
// is a filter, and removing it removes the filter. Searches are typed text
// matched against one level, or against all of them ("all"), and the Jobs list
// is built from the facets by loadJobs.
export class EquipmentModelDashboard extends Component {
    static template = "equipment_model.Dashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.searchInput = useRef("searchInput");
        this.state = useState({
            data: null,
            isManager: false,
            groupId: null,
            familyId: null,
            modelId: null,
            // Typed searches: {id, type, text, jobModelIds}. jobModelIds are the
            // Models with a Job whose name matches, for the "job" and "all" types.
            filters: [],
            query: "",
            searchOpen: false,
            highlighted: 0,
            jobs: [],
            jobCount: 0,
            loadingJobs: false,
        });
        this.jobsRequest = 0;
        this.nextFilterId = 1;
        onWillStart(async () => {
            [this.state.data, this.state.isManager] = await Promise.all([
                this.orm.call("equipment.model", "get_dashboard_data", []),
                user.hasGroup("equipment_model.group_equipment_model_manager"),
            ]);
        });
    }

    // Data

    get groupById() {
        return Object.fromEntries(this.state.data.groups.map((group) => [group.id, group]));
    }

    get familyById() {
        return Object.fromEntries(this.state.data.families.map((family) => [family.id, family]));
    }

    get modelById() {
        return Object.fromEntries(this.state.data.models.map((model) => [model.id, model]));
    }

    get searchTypes() {
        return [
            { type: "all", label: _t("All") },
            { type: "group", label: _t("Group") },
            { type: "family", label: _t("Product Family") },
            { type: "model", label: _t("Model") },
            { type: "job", label: _t("Job") },
        ];
    }

    typeLabel(type) {
        return this.searchTypes.find((searchType) => searchType.type === type).label;
    }

    // What is shown

    /** Does a Model match one typed search? */
    matchesModel(filter, model) {
        const family = this.familyById[model.family_id];
        const group = this.groupById[model.group_id];
        const text = filter.text;
        switch (filter.type) {
            case "model":
                return contains(model.name, text);
            case "family":
                return contains(family && family.name, text);
            case "group":
                return contains(group && group.name, text);
            case "job":
                return filter.jobModelIds.includes(model.id);
            default:
                return (
                    contains(model.name, text) ||
                    contains(family && family.name, text) ||
                    contains(group && group.name, text) ||
                    filter.jobModelIds.includes(model.id)
                );
        }
    }

    /** Models matching every typed search, whatever is picked. */
    get searchedModels() {
        const { filters, data } = this.state;
        return data.models.filter((model) => filters.every((filter) => this.matchesModel(filter, model)));
    }

    /** A Group or Family with no Model yet can only be found by its own name. */
    matchesEmpty(filter, ...names) {
        return ["group", "family", "all"].includes(filter.type) && names.some((name) => contains(name, filter.text));
    }

    get groups() {
        const { filters, data } = this.state;
        if (!filters.length) {
            return data.groups;
        }
        const found = new Set(this.searchedModels.map((model) => model.group_id));
        return data.groups.filter(
            (group) =>
                found.has(group.id) ||
                (!group.models && filters.every((filter) => this.matchesEmpty(filter, group.name)))
        );
    }

    get families() {
        const { filters, data, groupId } = this.state;
        const found = new Set(this.searchedModels.map((model) => model.family_id));
        return data.families.filter(
            (family) =>
                (groupId === null || family.group_id === groupId) &&
                (!filters.length ||
                    found.has(family.id) ||
                    (!family.models &&
                        filters.every((filter) =>
                            this.matchesEmpty(filter, family.name, this.groupById[family.group_id]?.name)
                        )))
        );
    }

    get models() {
        const { groupId, familyId } = this.state;
        return this.searchedModels.filter(
            (model) =>
                (groupId === null || model.group_id === groupId) &&
                (familyId === null || model.family_id === familyId)
        );
    }

    modelContext(model) {
        return {
            family: this.familyById[model.family_id]?.name || "",
            group: this.groupById[model.group_id]?.name || "",
        };
    }

    jobContext(job) {
        const model = job.model_id && this.modelById[job.model_id[0]];
        return model ? this.modelContext(model) : { family: "", group: "" };
    }

    barWidth(jobs, rows) {
        return `${Math.round((jobs / Math.max(1, ...rows.map((row) => row.jobs))) * 100)}%`;
    }

    // Facets

    /** Everything that filters, in the order it was applied: picked rows first. */
    get facets() {
        const { data, groupId, familyId, modelId, filters } = this.state;
        const facets = [];
        if (groupId !== null) {
            facets.push({ key: "group", label: _t("Group"), value: this.groupById[groupId]?.name });
        }
        if (familyId !== null) {
            facets.push({ key: "family", label: _t("Product Family"), value: this.familyById[familyId]?.name });
        }
        if (modelId !== null) {
            facets.push({ key: "model", label: _t("Model"), value: this.modelById[modelId]?.name });
        }
        for (const filter of filters) {
            facets.push({ key: filter.id, label: this.typeLabel(filter.type), value: filter.text, filter });
        }
        return facets;
    }

    removeFacet(facet) {
        if (facet.filter) {
            this.state.filters = this.state.filters.filter((filter) => filter !== facet.filter);
        } else {
            this.state[`${facet.key}Id`] = null;
        }
        this.loadJobs();
    }

    clearAll() {
        Object.assign(this.state, { groupId: null, familyId: null, modelId: null, filters: [] });
        this.loadJobs();
    }

    // Picking rows. Picking again what is picked unpicks it. Picking in a column
    // unpicks what was picked to its right: it was narrowed by what is replaced.

    selectGroup(id) {
        this.state.groupId = this.state.groupId === id ? null : id;
        this.state.familyId = null;
        this.state.modelId = null;
        this.loadJobs();
    }

    selectFamily(id) {
        this.state.familyId = this.state.familyId === id ? null : id;
        this.state.modelId = null;
        this.loadJobs();
    }

    selectModel(id) {
        this.state.modelId = this.state.modelId === id ? null : id;
        this.loadJobs();
    }

    // Search box

    get searchOptions() {
        return this.searchTypes;
    }

    focusSearch() {
        this.searchInput.el?.focus();
    }

    onSearchInput() {
        this.state.searchOpen = true;
        this.state.highlighted = 0;
    }

    onSearchKeydown(ev) {
        const { query, highlighted } = this.state;
        const count = this.searchOptions.length;
        if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
            ev.preventDefault();
            this.state.searchOpen = true;
            this.state.highlighted = (highlighted + (ev.key === "ArrowDown" ? 1 : count - 1)) % count;
        } else if (ev.key === "Enter" && query.trim()) {
            ev.preventDefault();
            this.addFilter(this.searchOptions[highlighted].type);
        } else if (ev.key === "Escape") {
            this.state.searchOpen = false;
        } else if (ev.key === "Backspace" && !query && this.facets.length) {
            this.removeFacet(this.facets.at(-1));
        }
    }

    async addFilter(type) {
        const text = this.state.query.trim();
        if (!text) {
            return;
        }
        const filter = { id: this.nextFilterId++, type, text, jobModelIds: [] };
        if (type === "job" || type === "all") {
            const jobs = await this.orm.searchRead("project.project", this.jobNameDomain(text), ["model_id"], {
                limit: MATCHING_JOBS_LIMIT,
            });
            filter.jobModelIds = [...new Set(jobs.filter((job) => job.model_id).map((job) => job.model_id[0]))];
        }
        this.state.filters.push(filter);
        this.state.query = "";
        this.state.searchOpen = false;
        this.loadJobs();
    }

    jobNameDomain(text) {
        return [...this.state.data.job_domain, ["name", "ilike", text]];
    }

    // Jobs

    /** The domain of the Jobs listed: every pick and every search, together. */
    get jobDomain() {
        const { data, groupId, familyId, modelId, filters } = this.state;
        const inModels = (models) => ["model_id", "in", models.map((model) => model.id)];
        const domain = [...data.job_domain];
        if (modelId !== null) {
            domain.push(["model_id", "=", modelId]);
        } else if (familyId !== null) {
            domain.push(inModels(data.models.filter((model) => model.family_id === familyId)));
        } else if (groupId !== null) {
            domain.push(inModels(data.models.filter((model) => model.group_id === groupId)));
        }
        for (const filter of filters) {
            // The Models whose own names match: a Job's name is matched by the domain itself.
            const names = inModels(data.models.filter((model) => this.matchesModel({ ...filter, jobModelIds: [] }, model)));
            if (filter.type === "job") {
                domain.push(["name", "ilike", filter.text]);
            } else if (filter.type === "all") {
                domain.push("|", ["name", "ilike", filter.text], names);
            } else {
                domain.push(names);
            }
        }
        return domain;
    }

    get hasCriteria() {
        return this.facets.length > 0;
    }

    async loadJobs() {
        const request = ++this.jobsRequest;
        if (!this.hasCriteria) {
            Object.assign(this.state, { jobs: [], jobCount: 0, loadingJobs: false });
            return;
        }
        this.state.loadingJobs = true;
        const domain = this.jobDomain;
        const [jobs, jobCount] = await Promise.all([
            this.orm.searchRead("project.project", domain, ["name", "model_id", "stage_id", "partner_id"], {
                limit: JOB_LIMIT,
                order: "name desc",
            }),
            this.orm.searchCount("project.project", domain),
        ]);
        if (request === this.jobsRequest) {
            Object.assign(this.state, { jobs, jobCount, loadingJobs: false });
        }
    }

    // Opening records

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

    openAllJobs() {
        this.open("project.project", _t("Jobs"), this.jobDomain);
    }

    openJobsWithoutModel() {
        this.open("project.project", _t("Jobs without a Model"), [
            ...this.state.data.job_domain,
            ["model_id", "=", false],
        ]);
    }

    openJob(job) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "project.project",
            res_id: job.id,
            views: [[false, "form"]],
        });
    }

    openGroup(group) {
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
        // What was picked may be gone, or may have moved elsewhere.
        const { groupId, familyId, modelId } = this.state;
        if (modelId !== null && !this.modelById[modelId]) {
            this.state.modelId = null;
        }
        if (familyId !== null && !this.familyById[familyId]) {
            this.state.familyId = this.state.modelId = null;
        }
        if (groupId !== null && !this.groupById[groupId]) {
            this.state.groupId = this.state.familyId = this.state.modelId = null;
        }
        await this.loadJobs();
    }
}

registry.category("actions").add("equipment_model_dashboard", EquipmentModelDashboard);
