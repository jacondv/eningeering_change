/** @odoo-module **/

import { registry } from "@web/core/registry";
import { ListController } from "@web/views/list/list_controller";
import { listView } from "@web/views/list/list_view";

/** The list's own New button opens the editor page instead of a blank form. */
export class QcChecksheetListController extends ListController {
    async createRecord() {
        await this.actionService.doAction("qc_checksheet.action_qc_checksheet_editor");
    }
}

registry.category("views").add("qc_checksheet_list", {
    ...listView,
    Controller: QcChecksheetListController,
});
