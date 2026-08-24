import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { StatusBarField } from "@web/views/fields/statusbar/statusbar_field";

// Changing a Part Number's state (e.g. Development -> Production) is a
// meaningful workflow step, so clicking a new value on the statusbar asks
// for confirmation first instead of applying instantly. window.confirm
// (rather than Odoo's own ConfirmationDialog service) keeps this to a
// single native prompt - see jacon_core's project_stage_confirm_patch.js
// for the same choice on Project's own Stage field. Scoped tightly to
// part_number_manager.part_number's own `state` field, so no other model's
// statusbar widget is affected.
patch(StatusBarField.prototype, {
    async selectItem(item) {
        const { name, record } = this.props;
        if (record.resModel !== "part_number_manager.part_number" || name !== "state" || item.isSelected) {
            return super.selectItem(...arguments);
        }
        if (!window.confirm(_t('Change this Part Number\'s state to "%s"?', item.label))) {
            return;
        }
        return super.selectItem(...arguments);
    },
});
