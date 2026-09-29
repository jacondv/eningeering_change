import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { KanbanRenderer } from "@web/views/kanban/kanban_renderer";

// Dragging a Support Request card to another Stage column asks for
// confirmation, same as clicking the form's statusbar (see statusbar_confirm).
patch(KanbanRenderer.prototype, {
    async sortRecordDrop(dataRecordId, dataGroupId, params) {
        const list = this.props.list;
        const targetGroupId = params.parent?.dataset.id;
        const isStageMove =
            list.resModel === "product.support.request" &&
            list.groupByField?.name === "state" &&
            targetGroupId &&
            targetGroupId !== params.element.parentElement.dataset.id;
        if (!isStageMove) {
            return super.sortRecordDrop(...arguments);
        }
        const targetGroup = list.groups.find((g) => String(g.id) === String(targetGroupId));
        const confirmed = await new Promise((resolve) => {
            this.dialog.add(ConfirmationDialog, {
                body: _t('Move this record to "%s"?', targetGroup?.displayName || ""),
                confirm: () => resolve(true),
                cancel: () => resolve(false),
            });
        });
        if (!confirmed) {
            // The card was already moved in the DOM by the drag helper; the
            // data didn't change, so re-rendering snaps it back.
            this.render();
            return;
        }
        return super.sortRecordDrop(...arguments);
    },
});
