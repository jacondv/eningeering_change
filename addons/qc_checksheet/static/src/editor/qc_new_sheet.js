/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { QcJobPicker } from "./qc_job_picker";

const CHECKSHEET_MODEL = "qc.checksheet";

/** The New Check Sheet page: pick the Job and Type, and what to start from. */
export class QcNewSheet extends Component {
    static template = "qc_checksheet.NewSheet";
    static components = { QcJobPicker };
    static props = {
        onCreated: Function,
        onOpen: Function,
        onBack: Function,
        defaultJobId: { type: [Number, Boolean], optional: true },
        defaultTypeId: { type: [Number, Boolean], optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = useState({
            types: [],
            typeId: false,
            job: null,
            header: "",
            headerIsAuto: false,
            source: "blank",
            sourceId: false,
            sourceJob: null,
            context: this.emptyContext(),
            creating: false,
        });
        this.searchJobs = (term) => this.orm.call(CHECKSHEET_MODEL, "editor_search_jobs", [term]);
        this.searchSourceJobs = (term) =>
            this.orm.call(CHECKSHEET_MODEL, "editor_search_source_jobs", [this.state.typeId, term]);

        onWillStart(async () => {
            this.state.types = await this.orm.call(CHECKSHEET_MODEL, "editor_types", []);
            const { defaultJobId, defaultTypeId } = this.props;
            this.state.typeId = this.state.types.some((type) => type.id === defaultTypeId)
                ? defaultTypeId
                : this.state.types[0]?.id || false;
            await this.refreshContext();
            if (defaultJobId) {
                const job = await this.orm.call(CHECKSHEET_MODEL, "editor_job_info", [defaultJobId]);
                if (job) {
                    await this.pickJob(job);
                }
            }
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

    async pickJob(job) {
        this.state.job = job;
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
        await this.refreshContext();
    }

    async pickSourceJob(job) {
        this.state.sourceJob = job;
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
