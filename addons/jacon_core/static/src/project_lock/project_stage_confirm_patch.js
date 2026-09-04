import { patch } from "@web/core/utils/patch";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";
import { user } from "@web/core/user";
import { StatusBarField } from "@web/views/fields/statusbar/statusbar_field";

// Moving a Project between stages is restricted to Head Office/Admin (see
// models/project_project.py) - check that up front so an unauthorized user
// gets a plain notification instead of clicking through a confirm dialog
// only to hit a server AccessError afterward. Allowed users then get
// Odoo's own ConfirmationDialog (same look as the Kanban drag-and-drop
// confirm in project_stage_confirm.js) rather than a browser-native
// window.confirm popup. This is the ONLY patch on StatusBarField.selectItem
// for project.project's stage_id - a second one used to live in
// project_stage_confirm.js too, firing right after this one on every click;
// that patch was removed there, keeping only its separate Kanban
// drag-and-drop confirm (a different code path, not affected by this
// file). Scoped to project.project only, via the resModel check below, so
// no other model's statusbar widget is affected.
patch(StatusBarField.prototype, {
    async selectItem(item) {
        if (this.props.record.resModel !== "project.project" || item.isSelected) {
            return super.selectItem(item);
        }
        const allowed = user.isAdmin || await user.hasGroup("jacon_core.group_head_office");
        if (!allowed) {
            this.env.services.notification.add(
                _t("Only the Engineering Head or an Administrator can change a Project's Stage."),
                { type: "danger" }
            );
            return;
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
        return super.selectItem(item);
    },
});
