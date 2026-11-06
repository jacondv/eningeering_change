/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { useDebounced } from "@web/core/utils/timing";
import { useService } from "@web/core/utils/hooks";

const CHECKSHEET_MODEL = "qc.checksheet";
const SEARCH_DEBOUNCE_MS = 250;

/** The New Check Sheet page: pick the Job and Type, and what to start from. */
export class QcNewSheet extends Component {
    static template = "qc_checksheet.NewSheet";
    static props = {
        onCreated: Function,
        onOpen: Function,
        onBack: Function,
    };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = useState({
            types: [],
            typeId: false,
            jobTerm: "",
            job: null,
            jobResults: [],
            jobMenuOpen: false,
            header: "",
            headerIsAuto: false,
            source: "blank",
            sourceId: false,
            sourceJob: null,
            sourceJobTerm: "",
            sourceJobResults: [],
            sourceJobMenuOpen: false,
            context: this.emptyContext(),
            creating: false,
        });
        this.searchJobs = useDebounced(this.searchJobs.bind(this), SEARCH_DEBOUNCE_MS);
        this.searchSourceJobs = useDebounced(this.searchSourceJobs.bind(this), SEARCH_DEBOUNCE_MS);

        onWillStart(async () => {
            this.state.types = await this.orm.call(CHECKSHEET_MODEL, "editor_types", []);
            this.state.typeId = this.state.types[0]?.id || false;
            await this.refreshContext();
        });
    }

    emptyContext() {
        return { number: "", header: "", model: "", serial: "", engine: "", customer: "", duplicate_id: false, sources: [] };
    }

    get selectedType() {
        return this.state.types.find((type) => type.id === this.state.typeId);
    }

    get previewNumber() {
        return this.state.context.number || `QC-${this.selectedType?.code || "?"}-[Model]`;
    }

    get headerHint() {
        if (this.state.headerIsAuto) {
            return "Filled in from the Product Family Description. You can change it.";
        }
        if (this.state.job && !this.state.context.header) {
            return "This Product Family has no Description, so type the Header.";
        }
        return "Printed as the top line of the PDF.";
    }

    get cannotCreate() {
        const { job, header, typeId, source, sourceId, context, creating } = this.state;
        return (
            creating ||
            !job ||
            !typeId ||
            !header.trim() ||
            !!context.duplicate_id ||
            (source === "copy" && !sourceId)
        );
    }

    async refreshContext() {
        const { job, typeId, sourceJob } = this.state;
        this.state.context = await this.orm.call(CHECKSHEET_MODEL, "editor_new_context", [
            job?.id || false,
            typeId,
            sourceJob?.id || false,
        ]);
        const { context } = this.state;
        if (!context.sources.some((source) => source.id === this.state.sourceId)) {
            this.state.sourceId = false;
        }
    }

    async searchJobs() {
        this.state.jobResults = await this.orm.call(CHECKSHEET_MODEL, "editor_search_jobs", [
            this.state.jobTerm,
        ]);
    }

    onJobInput(ev) {
        this.state.jobTerm = ev.target.value;
        this.state.jobMenuOpen = true;
        this.searchJobs();
    }

    onJobFocus() {
        this.state.jobMenuOpen = true;
        this.searchJobs();
    }

    onJobBlur() {
        // A click on a result blurs the input first, so let that click land.
        setTimeout(() => {
            this.state.jobMenuOpen = false;
            this.state.jobTerm = this.state.job?.name || "";
        }, 150);
    }

    async pickJob(job) {
        this.state.job = job;
        this.state.jobTerm = job.name;
        this.state.jobMenuOpen = false;
        await this.refreshContext();
        // Keep following the Job until the user types a Header of their own.
        if (!this.state.header || this.state.headerIsAuto) {
            this.state.header = this.state.context.header;
            this.state.headerIsAuto = !!this.state.context.header;
        }
    }

    async onTypeChange(ev) {
        this.state.typeId = parseInt(ev.target.value);
        // That Job may have nothing to copy for the new Type.
        this.state.sourceJob = null;
        this.state.sourceJobTerm = "";
        await this.refreshContext();
    }

    async searchSourceJobs() {
        this.state.sourceJobResults = await this.orm.call(CHECKSHEET_MODEL, "editor_search_source_jobs", [
            this.state.typeId,
            this.state.sourceJobTerm,
        ]);
    }

    onSourceJobInput(ev) {
        this.state.sourceJobTerm = ev.target.value;
        this.state.sourceJobMenuOpen = true;
        this.searchSourceJobs();
    }

    onSourceJobFocus() {
        this.state.sourceJobMenuOpen = true;
        this.searchSourceJobs();
    }

    onSourceJobBlur() {
        setTimeout(() => {
            this.state.sourceJobMenuOpen = false;
            this.state.sourceJobTerm = this.state.sourceJob?.name || "";
        }, 150);
    }

    async pickSourceJob(job) {
        this.state.sourceJob = job;
        this.state.sourceJobTerm = job ? job.name : "";
        this.state.sourceJobMenuOpen = false;
        await this.refreshContext();
    }

    onHeaderInput(ev) {
        this.state.header = ev.target.value;
        this.state.headerIsAuto = false;
    }

    async create() {
        if (this.cannotCreate) {
            return;
        }
        const { job, typeId, header, source, sourceId } = this.state;
        this.state.creating = true;
        try {
            const created = await this.orm.call(CHECKSHEET_MODEL, "editor_create", [
                {
                    job_id: job.id,
                    type_id: typeId,
                    header: header.trim(),
                    source_id: source === "copy" ? sourceId : false,
                },
            ]);
            this.props.onCreated(created);
        } finally {
            this.state.creating = false;
        }
    }
}
