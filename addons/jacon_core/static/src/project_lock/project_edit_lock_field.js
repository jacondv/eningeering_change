import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { ProjectUnlockDialog } from "./project_unlock_dialog";

export class ProjectEditLockField extends Component {
    static template = "jacon_core.ProjectEditLockField";
    static props = { ...standardFieldProps };

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
    }

    get isNewRecord() {
        return !this.props.record.resId;
    }

    get isUnlocked() {
        return this.props.record.data[this.props.name];
    }

    openUnlockDialog() {
        this.dialog.add(ProjectUnlockDialog, {
            onConfirm: async (password) => {
                const ok = await this.orm.call(
                    this.props.record.resModel,
                    "check_edit_password",
                    [[this.props.record.resId], password]
                );
                if (ok) {
                    await this.props.record.update({ [this.props.name]: true });
                }
                return ok;
            },
        });
    }

    lock() {
        this.props.record.update({ [this.props.name]: false });
    }
}

export const projectEditLockField = {
    component: ProjectEditLockField,
};

registry.category("fields").add("project_edit_lock_button", projectEditLockField);
