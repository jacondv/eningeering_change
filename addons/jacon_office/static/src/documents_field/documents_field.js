import { Component, onMounted, onWillStart, onWillUnmount, useRef, useState } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { AutoComplete } from "@web/core/autocomplete/autocomplete";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { deserializeDateTime, formatDateTime } from "@web/core/l10n/dates";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

const MODEL = "jacon.office.document";
const FIELDS = [
    "name", "kind", "category_id", "author", "last_edit_user_id", "last_edit_date", "revision",
    "version_count", "file_size_text", "pdf_state", "is_locked", "active",
];
const KIND_LABELS = { docx: _t("Word"), xlsx: _t("Excel"), pptx: _t("PowerPoint") };

/**
 * The Documents tab of a record that owns Office Documents (`jacon.office.mixin`).
 *
 * Put it on the mixin's `office_document_count` field. It lists the record's documents itself,
 * rather than through the form's own one2many list, so that it can offer what that list can't:
 * ticking several rows for bulk actions, editing a name/category/author in place, and keeping
 * working while the record's form is read-only. What a user may actually do is still decided
 * on the server, by their access to the record.
 */
export class OfficeDocumentsField extends Component {
    static template = "jacon_office.DocumentsField";
    static components = { AutoComplete, Dropdown, DropdownItem };
    static props = { ...standardFieldProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.state = useState({
            loaded: false,
            docs: [],
            categories: [],
            users: [],
            query: "",
            showArchived: false,
            selected: [],
            // Changes whenever the rows must be drawn afresh, e.g. to put back a value the server refused.
            version: 0,
        });
        this.root = useRef("root");
        this.loadSeq = 0;
        this.authorSources = new Map();
        // Coming back from the editor's tab: show what changed there. Not while something is being
        // typed in a row: the half-typed value would be wiped.
        this.onFocus = () => {
            const active = document.activeElement;
            if (!(active && this.root.el?.contains(active) && active.matches("input, select"))) {
                this.load();
            }
        };
        onWillStart(async () => {
            const [categories, users] = await Promise.all([
                this.orm.searchRead("jacon.office.category", [], ["name"], { order: "sequence, name" }),
                this.orm.searchRead("res.users", [["share", "=", false]], ["name"], { order: "name", limit: 500 }),
            ]);
            this.state.categories = categories;
            this.state.users = users;
            await this.load();
        });
        onMounted(() => window.addEventListener("focus", this.onFocus));
        onWillUnmount(() => window.removeEventListener("focus", this.onFocus));
    }

    get resModel() {
        return this.props.record.resModel;
    }

    get resId() {
        return this.props.record.resId;
    }

    get rows() {
        const query = this.state.query.trim().toLowerCase();
        return query
            ? this.state.docs.filter((doc) => doc.name.toLowerCase().includes(query))
            : this.state.docs;
    }

    /** The ticked documents that are also on screen: a search can hide some, and they must not be acted on. */
    get selection() {
        return this.state.selected.filter((id) => this.rows.some((doc) => doc.id === id));
    }

    get allSelected() {
        return this.rows.length > 0 && this.rows.every((doc) => this.state.selected.includes(doc.id));
    }

    kindLabel(kind) {
        return KIND_LABELS[kind] || kind;
    }

    formatDate(value) {
        return value ? formatDateTime(deserializeDateTime(value)) : "";
    }

    async load() {
        const seq = ++this.loadSeq;
        if (!this.resId) {
            this.state.docs = [];
            this.state.loaded = true;
            return;
        }
        const docs = await this.orm.searchRead(
            MODEL,
            [
                ["res_model", "=", this.resModel],
                ["res_id", "=", this.resId],
                ["active", "=", !this.state.showArchived],
            ],
            FIELDS,
            { order: "id desc", context: { active_test: false } }
        );
        if (seq !== this.loadSeq) {
            return; // a newer load was started meanwhile: its answer is the one to show
        }
        this.state.docs = docs;
        this.state.selected = this.state.selected.filter((id) => docs.some((doc) => doc.id === id));
        this.state.loaded = true;
    }

    // -- selection ---------------------------------------------------

    isSelected(id) {
        return this.state.selected.includes(id);
    }

    toggleSelected(id) {
        this.state.selected = this.isSelected(id)
            ? this.state.selected.filter((selectedId) => selectedId !== id)
            : [...this.state.selected, id];
    }

    toggleAll() {
        this.state.selected = this.allSelected ? [] : this.rows.map((doc) => doc.id);
    }

    clearSelection() {
        this.state.selected = [];
    }

    async toggleArchived() {
        this.state.showArchived = !this.state.showArchived;
        this.state.selected = [];
        await this.load();
    }

    // -- one document ------------------------------------------------

    async newDocument() {
        const action = await this.orm.call(this.resModel, "action_new_office_document", [[this.resId]]);
        await this.action.doAction(action, { onClose: () => this.load() });
    }

    async openAction(doc, method) {
        const action = await this.orm.call(MODEL, method, [[doc.id]]);
        await this.action.doAction(action, { onClose: () => this.load() });
    }

    /**
     * Shows what the server answers in a new tab. The tab is opened right on the click: a browser
     * only allows that, not a tab opened after waiting for the server (which making a PDF can take).
     */
    async openInTab(doc, method) {
        const tab = browser.open("", "_blank");
        try {
            const action = await this.orm.call(MODEL, method, [[doc.id]]);
            if (tab && action.type === "ir.actions.act_url") {
                tab.location = action.url;
            } else {
                tab?.close();
                await this.action.doAction(action);
            }
        } catch (error) {
            tab?.close();
            throw error;
        } finally {
            await this.load();
        }
    }

    viewPdf(doc) {
        return this.openInTab(doc, "action_view_pdf");
    }

    edit(doc) {
        return this.openInTab(doc, "action_open_editor");
    }

    async versions(doc) {
        await this.openAction(doc, "action_view_versions");
        await this.load(); // a Rev may have been restored or deleted
    }

    download(doc) {
        return this.openAction(doc, "action_download");
    }

    /** Writes a value typed or picked in a row; the row shows what the server kept (or goes back). */
    async setField(doc, field, value) {
        let refused = false;
        try {
            await this.orm.write(MODEL, [doc.id], { [field]: value });
        } catch (error) {
            refused = true;
            throw error;
        } finally {
            await this.load();
            if (refused) {
                this.state.version++;
            }
        }
    }

    rename(doc, ev) {
        const name = ev.target.value.trim();
        if (!name || name === doc.name) {
            ev.target.value = doc.name;
            return;
        }
        return this.setField(doc, "name", name);
    }

    setMany2one(doc, field, ev) {
        return this.setField(doc, field, ev.target.value ? parseInt(ev.target.value, 10) : false);
    }

    /**
     * What the Author box offers while typing: the users' names. Anything else can be typed too, so
     * the box also keeps the text as it is (see `authorChanged`).
     */
    authorOptions(doc) {
        if (!this.authorSources.has(doc.id)) {
            this.authorSources.set(doc.id, [
                {
                    options: (request) => {
                        const query = request.trim().toLowerCase();
                        return this.state.users
                            .filter((user) => user.name.toLowerCase().includes(query))
                            .slice(0, 10)
                            .map((user) => ({
                                label: user.name,
                                onSelect: () => this.setField(doc, "author", user.name),
                            }));
                    },
                },
            ]);
        }
        return this.authorSources.get(doc.id);
    }

    authorChanged(doc, { inputValue, isOptionSelected }) {
        const author = inputValue.trim();
        if (!isOptionSelected && author !== (doc.author || "")) {
            return this.setField(doc, "author", author || false);
        }
    }

    // -- the selected documents --------------------------------------

    async bulk(callback) {
        try {
            await callback(this.selection);
        } finally {
            await this.load();
        }
    }

    archive() {
        return this.bulk((ids) => this.orm.call(MODEL, "action_archive", [ids]));
    }

    unarchive() {
        return this.bulk((ids) => this.orm.call(MODEL, "action_unarchive", [ids]));
    }

    deleteOldRevs() {
        const count = this.selection.length;
        this.dialog.add(ConfirmationDialog, {
            title: _t("Delete old Revs"),
            body: _t(
                "Delete every previous Rev of the %s selected document(s)? Their current content is kept.",
                count
            ),
            confirmLabel: _t("Delete old Revs"),
            confirm: () =>
                this.bulk(async (ids) => {
                    const action = await this.orm.call(MODEL, "action_delete_old_versions", [ids]);
                    await this.action.doAction(action);
                }),
            cancel: () => {},
        });
    }

    deleteSelected() {
        const count = this.selection.length;
        this.dialog.add(ConfirmationDialog, {
            title: _t("Delete documents"),
            body: _t(
                "Delete %s document(s), with all their Revs? This cannot be undone. Archiving keeps them out of the way without deleting.",
                count
            ),
            confirmLabel: _t("Delete"),
            confirm: () => this.bulk((ids) => this.orm.unlink(MODEL, ids)),
            cancel: () => {},
        });
    }
}

registry.category("fields").add("jacon_office_documents", {
    component: OfficeDocumentsField,
    displayName: _t("Office Documents"),
    supportedTypes: ["integer"],
});
