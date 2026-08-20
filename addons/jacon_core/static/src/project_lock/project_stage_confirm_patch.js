import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { user } from "@web/core/user";
import { StatusBarField } from "@web/views/fields/statusbar/statusbar_field";

// Moving a Project between stages is restricted to Head Office/Admin (see
// models/project_project.py) - check that up front so an unauthorized user
// gets a plain notification instead of clicking through a confirm dialog
// only to hit a server AccessError afterward. Authorized users still get a
// single native confirm (not Odoo's own ConfirmationDialog service, which
// was firing alongside another "Confirmation" popup for this same click -
// window.confirm sidesteps that entirely and is simpler for a plain
// yes/no). Scoped to project.project only, via the resModel check below,
// so no other model's statusbar widget is affected.
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
        if (!window.confirm(_t('Move this project to "%s"?', item.label))) {
            return;
        }
        return super.selectItem(item);
    },
});
