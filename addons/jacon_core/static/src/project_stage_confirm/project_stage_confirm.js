import { patch } from "@web/core/utils/patch";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { KanbanRenderer } from "@web/views/kanban/kanban_renderer";
import { _t } from "@web/core/l10n/translation";
import { user } from "@web/core/user";

// Project's Stage change is a meaningful workflow step, so dragging a card
// to another Kanban column asks for confirmation first instead of applying
// instantly - same idea as the statusbar's own confirm, in
// project_lock/project_stage_confirm_patch.js (that file also patches
// StatusBarField.selectItem for this same stage_id change; the two used to
// both patch StatusBarField and fire one after another - see that file's
// comment for why it was consolidated there instead of here). Scoped
// tightly to project.project's own stage_id, so no other model's Kanban
// behavior is affected by this patch.

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
        // Same permission pre-check as the statusbar patch - without it, a
        // non-Head-Office/Admin user could drag a card, confirm, and only
        // then hit the server's AccessError.
        const allowed = user.isAdmin || await user.hasGroup("jacon_core.group_head_office");
        if (!allowed) {
            this.env.services.notification.add(
                _t("Only the Engineering Head or an Administrator can change a Project's Stage."),
                { type: "danger" }
            );
            this.render();
            return;
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
