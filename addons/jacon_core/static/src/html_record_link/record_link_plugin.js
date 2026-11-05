import { isHtmlContentSupported } from "@html_editor/core/selection_plugin";
import { Plugin } from "@html_editor/plugin";
import { closestElement } from "@html_editor/utils/dom_traversal";
import { withSequence } from "@html_editor/utils/resource";
import { _t } from "@web/core/l10n/translation";
import { RecordLinkDialog, recordLinkTypes } from "./record_link_dialog";

recordLinkTypes.add("task", {
    label: _t("Task"),
    prefix: _t("Task"),
    resModel: "project.task",
    actionPath: "all-tasks",
    titleField: "name",
    // The same templates the All Tasks action leaves out.
    domain: [["has_template_ancestor", "=", false], ["has_project_template", "=", false]],
    filter: {
        field: "project_id",
        resModel: "project.project",
        label: _t("Project"),
        placeholder: _t("All projects"),
        domain: [["is_template", "=", false]],
    },
}, { sequence: 10 });

recordLinkTypes.add("project", {
    label: _t("Project"),
    prefix: _t("Project"),
    resModel: "project.project",
    actionPath: "project",
    titleField: "name",
    domain: [["is_template", "=", false]],
}, { sequence: 40 });

// The `/` command that inserts a link to a record, picked by searching for it
// rather than by copying its URL. It's an ordinary link once inserted: nothing
// keeps its text up to date if the record is renamed.
export class RecordLinkPlugin extends Plugin {
    static id = "recordLink";
    static dependencies = ["dialog", "dom", "history", "link", "selection"];
    resources = {
        user_commands: {
            id: "insertRecordLink",
            title: _t("Link to Record"),
            description: _t("Search for a record and link to it"),
            icon: "fa-external-link",
            run: this.openDialog.bind(this),
            isAvailable: (selection) =>
                isHtmlContentSupported(selection) && !closestElement(selection.anchorNode, "a"),
        },
        powerbox_items: {
            categoryId: "navigation",
            commandId: "insertRecordLink",
            keywords: recordLinkTypes.getAll().map((type) => type.label),
        },
        // Between core's Upload (5) and Button (10), with the other insert commands.
        power_buttons: withSequence(9, {
            commandId: "insertRecordLink",
            description: _t("Link to Record"),
        }),
    };

    openDialog() {
        return this.dependencies.dialog.addDialog(RecordLinkDialog, {
            onSelect: this.insertLink.bind(this),
        });
    }

    insertLink(url, text) {
        const link = this.dependencies.link.createLink(url, text);
        link.setAttribute("target", "_blank");
        this.dependencies.dom.insert(link);
        this.dependencies.history.addStep();
        const parent = link.parentElement;
        this.dependencies.selection.setSelection(
            { anchorNode: parent, anchorOffset: [...parent.childNodes].indexOf(link) + 1 },
            { normalize: false }
        );
    }
}
