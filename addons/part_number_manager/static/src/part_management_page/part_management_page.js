/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const PART_NUMBER_MODEL = "part_number_manager.part_number";

export class PartManagementPage extends Component {
    static template = "part_number_manager.PartManagementPage";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");

        this.state = useState({
            activeTab: "create", // "create" | "convert"
            rows: [],
            errors: {},
            isSaving: false,
        });

        // Each *Options array is the datalist source for one autocomplete
        // field: [{id, label}]. Kept as plain (non-reactive) component
        // properties - inputs are uncontrolled (see part_management_page.xml)
        // so re-renders never fight the user's typing.
        this.materialGroupOptions = [];
        this.jobNumberOptions = [];
        this.vendorOptions = [];
        this.partTypeOptions = [];
        this.partTypes = [];
        this.attributeDefs = {}; // attribute_id -> {name, value_type, uom, options}
        this.allParts = []; // [{id, part_number, material_group_id, state}]

        onWillStart(async () => {
            await Promise.all([
                this._loadMaterialGroups(),
                this._loadJobNumbers(),
                this._loadVendors(),
                this._loadPartTypesAndAttributes(),
                this._loadAllParts(),
            ]);
            this.addRow();
        });
    }

    async _loadMaterialGroups() {
        const groups = await this.orm.searchRead(
            "part_number_manager.material_group", [], ["code", "description"]
        );
        this.materialGroupOptions = groups.map((g) => ({ id: g.id, label: `${g.code} - ${g.description}` }));
    }

    async _loadJobNumbers() {
        const jobs = await this.orm.searchRead("project.project", [], ["name"]);
        this.jobNumberOptions = jobs.filter((j) => j.name).map((j) => ({ id: j.id, label: j.name }));
    }

    async _loadVendors() {
        const vendors = await this.orm.searchRead("res.partner", [], ["name"]);
        this.vendorOptions = vendors.filter((v) => v.name).map((v) => ({ id: v.id, label: v.name }));
    }

    async _loadPartTypesAndAttributes() {
        this.partTypes = await this.orm.searchRead(
            "part_number_manager.part_type", [], ["name", "attribute_ids"]
        );
        this.partTypeOptions = this.partTypes.map((t) => ({ id: t.id, label: t.name }));
        const attributeIds = [...new Set(this.partTypes.flatMap((t) => t.attribute_ids))];
        if (!attributeIds.length) {
            return;
        }
        const attributes = await this.orm.read(
            "part_number_manager.part_attribute", attributeIds, ["name", "value_type", "uom"]
        );
        const options = await this.orm.searchRead(
            "part_number_manager.part_attribute_option",
            [["attribute_id", "in", attributeIds]],
            ["name", "attribute_id"]
        );
        for (const attr of attributes) {
            this.attributeDefs[attr.id] = {
                name: attr.name,
                value_type: attr.value_type,
                uom: attr.uom,
                options: options.filter((o) => o.attribute_id[0] === attr.id),
            };
        }
    }

    async _loadAllParts() {
        const parts = await this.orm.searchRead(
            PART_NUMBER_MODEL,
            [],
            ["part_number", "material_group_id", "state", "short_description", "long_description"]
        );
        // Records without a part_number yet (e.g. a draft saved from the
        // classic form before Generate ever ran) have nothing meaningful to
        // autocomplete against - drop them instead of shipping a broken
        // (non-string) label into the datalist.
        this.allParts = parts
            .filter((p) => p.part_number)
            .map((p) => ({
                id: p.id,
                label: p.part_number,
                material_group_id: p.material_group_id ? p.material_group_id[0] : false,
                state: p.state,
                short_description: p.short_description || "",
                long_description: p.long_description || "",
            }));
    }

    // Any part can be picked as the "Legacy Part Number" to convert -
    // regardless of Material Group (legacy codes predate the current
    // group/format rules, see techspec 2.2) and regardless of state: the
    // mapping is N-N, so an already-obsolete legacy code (superseded once
    // already) must stay pickable for a *second* new code pointing at it.
    // Excluding obsolete parts here would make the autocomplete miss it on
    // the second conversion and try to re-create it, hitting the
    // part_number unique constraint.
    get legacyOptions() {
        return this.allParts;
    }

    // Candidates for "attach to an existing Part Number" are scoped to the
    // row's own Material Group, and exclude the legacy part itself and any
    // already-obsolete part.
    getTargetOptions(row) {
        return this.allParts.filter((p) =>
            p.state !== "obsolete" &&
            p.material_group_id === row.material_group_id &&
            p.id !== row.conversion_legacy_id
        );
    }

    // Resolves free-typed text against a datalist's options by exact
    // (case-insensitive) label match. Anything else - partial text, a typo,
    // an empty string - resolves to `false` ("no selection"), which is
    // exactly what callers want: only a full match counts as a pick.
    resolveIdByLabel(options, text) {
        const norm = (text || "").trim().toLowerCase();
        if (!norm) {
            return false;
        }
        const match = options.find((o) => String(o.label || "").toLowerCase() === norm);
        return match ? match.id : false;
    }

    switchTab(tab) {
        this.state.activeTab = tab;
        if (!this.state.rows.some((r) => r.status !== "success")) {
            this.addRow();
        }
    }

    addRow() {
        this.state.rows.push({
            _localId: Date.now() + Math.random(),
            material_group_id: false,
            job_number: false,
            short_description: "",
            long_description: "",
            vendor_id: false,
            vendor_ref: "",
            part_type_id: false,
            attributes: [],
            conversion_legacy_id: false,
            legacyCodeText: "", // typed legacy code with no match - will be created on Save
            existing_new_part_id: false, // (convert tab only) resolved match, if any
            targetPartText: "", // (convert tab only) raw typed text - blank means "generate a new one"
            status: "pending", // pending | success | error
            resultPartNumber: null,
            errorMessage: null,
        });
    }

    removeRow(localId) {
        this.state.rows = this.state.rows.filter((r) => r._localId !== localId);
    }

    onMaterialGroupInput(row, ev) {
        row.material_group_id = this.resolveIdByLabel(this.materialGroupOptions, ev.target.value);
        // The target-part datalist is scoped to this Material Group - clear
        // a stale pick if the group changed underneath it.
        row.existing_new_part_id = false;
        row.targetPartText = "";
    }

    onJobNumberInput(row, ev) {
        row.job_number = this.resolveIdByLabel(this.jobNumberOptions, ev.target.value);
    }

    onVendorInput(row, ev) {
        row.vendor_id = this.resolveIdByLabel(this.vendorOptions, ev.target.value);
    }

    onAttributeValueChange(attr, value) {
        attr.value = value;
    }

    onPartTypeInput(row, ev) {
        const partTypeId = this.resolveIdByLabel(this.partTypeOptions, ev.target.value);
        row.part_type_id = partTypeId;
        if (!partTypeId) {
            row.attributes = [];
            return;
        }
        const partType = this.partTypes.find((t) => t.id === partTypeId);
        row.attributes = (partType ? partType.attribute_ids : []).map((attributeId) => {
            const def = this.attributeDefs[attributeId] || {};
            return {
                attribute_id: attributeId,
                name: def.name || "",
                value_type: def.value_type || "char",
                uom: def.uom || "",
                options: def.options || [],
                value: "",
            };
        });
    }

    // Old Part Number allows creating on the fly: unmatched text is kept as
    // pending "create" text instead of being discarded. Picking an existing
    // one auto-fills its Description into the row, so it doesn't need to be
    // retyped for the converted part.
    onLegacyPartInput(row, ev) {
        const text = ev.target.value;
        const id = this.resolveIdByLabel(this.legacyOptions, text);
        row.conversion_legacy_id = id;
        row.legacyCodeText = id ? "" : text.trim();
        if (id) {
            const legacy = this.legacyOptions.find((p) => p.id === id);
            row.short_description = legacy.short_description;
            row.long_description = legacy.long_description;
        }
    }

    // Leaving this blank means "generate a new Part Number" (handled
    // server-side, same as the Create New flow). Typing something is only
    // ever a pick from existing Part Numbers - a typo/no-match is an error,
    // it never silently falls back to generating an unrelated new part.
    onTargetPartInput(row, ev) {
        const text = ev.target.value;
        row.targetPartText = text.trim();
        row.existing_new_part_id = this.resolveIdByLabel(this.getTargetOptions(row), text);
    }

    validateClientSide() {
        const errors = {};
        for (const row of this.state.rows) {
            if (row.status === "success") continue;
            if (!row.material_group_id) errors[`${row._localId}_group`] = "Required";
            if (this.state.activeTab === "create" && !row.job_number) {
                errors[`${row._localId}_job`] = "Required";
            }
            if (this.state.activeTab === "convert") {
                if (!row.conversion_legacy_id && !row.legacyCodeText) {
                    errors[`${row._localId}_legacy`] = "Type or pick an Old Part Number to convert";
                }
                if (row.targetPartText && !row.existing_new_part_id) {
                    errors[`${row._localId}_target`] = "This Part Number does not exist";
                }
            }
        }
        this.state.errors = errors;
        return Object.keys(errors).length === 0;
    }

    // Only unsaved/failed rows are sent - rows already saved stay put and are
    // never resent, so clicking Save again can't create duplicates.
    async onSaveClick() {
        if (!this.validateClientSide()) {
            this.notification.add("Please fix the highlighted rows first.", { type: "danger" });
            return;
        }

        const pendingRows = this.state.rows.filter((r) => r.status !== "success");
        if (!pendingRows.length) {
            this.notification.add("Nothing to save.", { type: "info" });
            return;
        }

        this.state.isSaving = true;
        try {
            const payload = pendingRows.map((row) => ({
                material_group_id: row.material_group_id,
                job_number: row.job_number || false,
                short_description: row.short_description,
                long_description: row.long_description,
                vendor_id: row.vendor_id || false,
                vendor_ref: row.vendor_ref,
                part_type_id: row.part_type_id || false,
                attribute_values: row.attributes
                    .filter((a) => a.value)
                    .map((a) => ({ attribute_id: a.attribute_id, value: a.value })),
                conversion_legacy_id: row.conversion_legacy_id || null,
                conversion_legacy_text: row.conversion_legacy_id ? null : (row.legacyCodeText || null),
                existing_new_part_id: row.existing_new_part_id || null,
                target_part_text: row.existing_new_part_id ? null : (row.targetPartText || null),
            }));

            const results = await this.orm.call(
                PART_NUMBER_MODEL, "create_batch_with_generated_number", [payload]
            );

            results.forEach((res, i) => {
                const row = pendingRows[i];
                if (res.success) {
                    row.status = "success";
                    row.resultPartNumber = res.part_number;
                    row.errorMessage = null;
                } else {
                    row.status = "error";
                    row.errorMessage = res.error;
                }
            });

            if (this.state.activeTab === "convert") {
                await this._loadAllParts();
            }

            const successCount = results.filter((r) => r.success).length;
            const failCount = results.length - successCount;

            if (failCount === 0) {
                this.notification.add(`Successfully created ${successCount} part(s).`, { type: "success" });
                this.addRow();
            } else {
                this.notification.add(
                    `${successCount} succeeded, ${failCount} failed. ` +
                    `Please review and Save the failed rows again.`,
                    { type: "warning" }
                );
            }
        } finally {
            this.state.isSaving = false;
        }
    }
}

registry.category("actions").add("part_number_manager.part_management_page", PartManagementPage);
