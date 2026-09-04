import { patch } from "@web/core/utils/patch";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";
import { StatusBarField } from "@web/views/fields/statusbar/statusbar_field";

// Changing a Part Number's state (e.g. Development -> Production) is a
// meaningful workflow step, so clicking a new value on the statusbar asks
// for confirmation first instead of applying instantly. Uses Odoo's own
// ConfirmationDialog service, same as jacon_core's Project Stage confirm,
// for a consistent look across both. Scoped tightly to
// part_number_manager.part_number's own `state` field, so no other model's
// statusbar widget is affected.
patch(StatusBarField.prototype, {
    async selectItem(item) {
        const { name, record } = this.props;
        if (record.resModel !== "part_number_manager.part_number" || name !== "state" || item.isSelected) {
            return super.selectItem(...arguments);
        }
        const confirmed = await new Promise((resolve) => {
            this.env.services.dialog.add(ConfirmationDialog, {
                body: _t('Change this Part Number\'s state to "%s"?', item.label),
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
