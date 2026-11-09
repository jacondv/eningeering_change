/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { QcJobPicker } from "./qc_job_picker";

const CHECKSHEET_MODEL = "qc.checksheet";

/** The New Check Sheet page: pick the Model and Type, and what to start from. */
export class QcNewSheet extends Component {
    static template = "qc_checksheet.NewSheet";
    static components = { QcJobPicker };
    static props = {
        onCreated: Function,
        onOpen: Function,
        onBack: Function,
        defaultModelId: { type: [Number, Boolean], optional: true },
        defaultTypeId: { type: [Number, Boolean], optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = useState({
            types: [],
            typeId: false,
            model: null,
            header: "",
            headerIsAuto: false,
            source: "blank",
            sourceId: false,
            sourceModel: null,
            context: this.emptyContext(),
            creating: false,
        });
        this.searchModels = (term) => this.orm.call(CHECKSHEET_MODEL, "editor_search_models", [term]);
        this.searchSourceModels = (term) =>
            this.orm.call(CHECKSHEET_MODEL, "editor_search_source_models", [this.state.typeId, term]);

        onWillStart(async () => {
            this.state.types = await this.orm.call(CHECKSHEET_MODEL, "editor_types", []);
            const { defaultModelId, defaultTypeId } = this.props;
            this.state.typeId = this.state.types.some((type) => type.id === defaultTypeId)
                ? defaultTypeId
                : this.state.types[0]?.id || false;
            await this.refreshContext();
            if (defaultModelId) {
                const model = await this.orm.call(CHECKSHEET_MODEL, "editor_model_info", [defaultModelId]);
                if (model) {
                    await this.pickModel(model);
                }
            }
        });
    }

    emptyContext() {
        return { number: "", header: "", model: "", family: "", job_count: 0, duplicate_id: false, sources: [] };
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
        if (this.state.model && !this.state.context.header) {
            return "This Product Family has no Description, so type the Header.";
        }
        return "Printed as the top line of the PDF.";
    }

    get cannotCreate() {
        const { model, header, typeId, source, sourceId, context, creating } = this.state;
        return (
            creating ||
            !model ||
            !typeId ||
            !header.trim() ||
            !!context.duplicate_id ||
            (source === "copy" && !sourceId)
        );
    }

    async refreshContext() {
        const { model, typeId, sourceModel } = this.state;
        this.state.context = await this.orm.call(CHECKSHEET_MODEL, "editor_new_context", [
            model?.id || false,
            typeId,
            sourceModel?.id || false,
        ]);
        const { context } = this.state;
        if (!context.sources.some((source) => source.id === this.state.sourceId)) {
            this.state.sourceId = false;
        }
    }

    async pickModel(model) {
        this.state.model = model;
        await this.refreshContext();
        // Keep following the Model until the user types a Header of their own.
        if (!this.state.header || this.state.headerIsAuto) {
            this.state.header = this.state.context.header;
            this.state.headerIsAuto = !!this.state.context.header;
        }
    }

    async onTypeChange(ev) {
        this.state.typeId = parseInt(ev.target.value);
        // That Model may have nothing to copy for the new Type.
        this.state.sourceModel = null;
        await this.refreshContext();
    }

    async pickSourceModel(model) {
        this.state.sourceModel = model;
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
        const { model, typeId, header, source, sourceId } = this.state;
        this.state.creating = true;
        try {
            const created = await this.orm.call(CHECKSHEET_MODEL, "editor_create", [
                {
                    model_id: model.id,
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
