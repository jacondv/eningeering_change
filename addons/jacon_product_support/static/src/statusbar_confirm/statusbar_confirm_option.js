import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { StatusBarField, statusBarField } from "@web/views/fields/statusbar/statusbar_field";

// Opt-in `confirm` option on the standard statusbar widget:
//   <field name="state" widget="statusbar" options="{'clickable': '1', 'confirm': '1'}"/>
// Stays the core widget (not a subclass under a new name) so every core
// .o_field_statusbar style still applies.
const superExtractProps = statusBarField.extractProps;
patch(statusBarField, {
    extractProps(fieldInfo, dynamicInfo) {
        return {
            ...superExtractProps(fieldInfo, dynamicInfo),
            confirm: Boolean(fieldInfo.options.confirm),
        };
    },
});

patch(StatusBarField, {
    props: { ...StatusBarField.props, confirm: { type: Boolean, optional: true } },
});

patch(StatusBarField.prototype, {
    async selectItem(item) {
        if (!this.props.confirm || item.isSelected) {
            return super.selectItem(item);
        }
        const confirmed = await new Promise((resolve) => {
            this.env.services.dialog.add(ConfirmationDialog, {
                body: _t('Move this record to "%s"?', item.label),
                confirm: () => resolve(true),
                cancel: () => resolve(false),
            });
        });
        if (confirmed) {
            return super.selectItem(item);
        }
    },
});
