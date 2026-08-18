import { patch } from "@web/core/utils/patch";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { KanbanRenderer } from "@web/views/kanban/kanban_renderer";
import { StatusBarField } from "@web/views/fields/statusbar/statusbar_field";
import { _t } from "@web/core/l10n/translation";

// Project's Stage change is a meaningful workflow step (unlike most other
// Kanban/statusbar drags), so both ways of changing it - dragging a card to
// another Kanban column, or clicking a stage on the form's statusbar - ask
// for confirmation first instead of applying instantly. Scoped tightly to
// project.project's own stage_id everywhere below, so no other model's
// Kanban/statusbar behavior is affected by this patch.

patch(KanbanRenderer.prototype, {
    async sortRecordDrop(dataRecordId, dataGroupId, params) {
        const list = this.props.list;
        const targetGroupId = params.parent?.dataset.id;
        const isProjectStageMove =
            list.resModel === "project.project" &&
            list.groupByField?.name === "stage_id" &&
            targetGroupId &&
            targetGroupId !== params.element.parentElement.dataset.id;
        if (!isProjectStageMove) {
            return super.sortRecordDrop(...arguments);
        }
        const record = list.records.find((r) => r.id === dataRecordId);
        const targetGroup = list.groups.find((g) => String(g.id) === String(targetGroupId));
        const confirmed = await new Promise((resolve) => {
            this.dialog.add(ConfirmationDialog, {
                body: _t(
                    'Move project "%(project)s" to stage "%(stage)s"?',
                    { project: record?.data?.display_name || "", stage: targetGroup?.displayName || "" }
                ),
                confirm: () => resolve(true),
                cancel: () => resolve(false),
            });
        });
        if (!confirmed) {
            // The drag helper already moved the DOM element into the target
            // column before this handler runs - since the underlying data
            // never changed, a re-render snaps it back to its real group.
            this.render();
            return;
        }
        return super.sortRecordDrop(...arguments);
    },
});

patch(StatusBarField.prototype, {
    async selectItem(item) {
        const { name, record } = this.props;
        if (record.resModel !== "project.project" || name !== "stage_id") {
            return super.selectItem(...arguments);
        }
        const confirmed = await new Promise((resolve) => {
            this.env.services.dialog.add(ConfirmationDialog, {
                body: _t('Move this Project to stage "%s"?', item.label),
                confirm: () => resolve(true),
                cancel: () => resolve(false),
            });
        });
        if (!confirmed) {
            return;
        }
        return super.selectItem(...arguments);
    },
});
