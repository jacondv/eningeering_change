import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { StatusBarField } from "@web/views/fields/statusbar/statusbar_field";

// Moving a Project between stages can be a meaningful, hard-to-undo action
// (it can also lock the project entirely once it reaches a closed stage -
// see security/project_project_rules.xml) - ask for confirmation before
// actually committing it. Scoped to project.project only, via the
// resModel check below, so no other model's statusbar widget is affected.
patch(StatusBarField.prototype, {
    async selectItem(item) {
        if (this.props.record.resModel !== "project.project" || item.isSelected) {
            return super.selectItem(item);
        }
        return new Promise((resolve) => {
            this.env.services.dialog.add(ConfirmationDialog, {
                title: _t("Confirm Stage Change"),
                body: _t('Move this project to "%s"?', item.label),
                confirm: async () => {
                    await super.selectItem(item);
                    resolve();
                },
                cancel: () => resolve(),
            });
        });
    },
});
