/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useState, onWillStart, onMounted } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { ListController } from "@web/views/list/list_controller";
import { jaconCoreListView } from "@jacon_core/list/left_align_number_list_view";

// Remembered per-browser (not per-user record) so switching it doesn't
// touch the DB - same idea as part_management_page's own column widths/
// active tab storage.
const DISPLAY_CURRENCY_STORAGE_KEY = "part_number_manager.part_number_list.display_currency_id";

// Adds a "Display In" currency picker to the Part Number list's control
// panel. Picking a currency sets display_currency_id in the list's search
// context, which part_number.py's price_display compute field (@api.
// depends_context) reads server-side to convert every row's Price on the
// fly - no data on the record itself ever changes.
export class PnmPartNumberListController extends ListController {
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.pnmState = useState({
            currencies: [],
            displayCurrencyId: this._loadStoredDisplayCurrencyId(),
        });
        onWillStart(async () => {
            this.pnmState.currencies = await this.orm.searchRead(
                "res.currency", [["active", "=", true]], ["id", "name"], { order: "name" }
            );
        });
        // The very first load (before this component ever mounts) reads
        // context from the SearchModel, not from anything set here - so a
        // remembered choice needs one extra reload right after mount to
        // actually apply to that first page of data, rather than only
        // taking effect the next time the picker itself is touched.
        onMounted(() => {
            if (this.pnmState.displayCurrencyId) {
                this.model.load({
                    context: { ...this.model.config.context, display_currency_id: this.pnmState.displayCurrencyId },
                });
            }
        });
    }

    _loadStoredDisplayCurrencyId() {
        try {
            const stored = localStorage.getItem(DISPLAY_CURRENCY_STORAGE_KEY);
            return stored ? Number(stored) : null;
        } catch {
            return null;
        }
    }

    onDisplayCurrencyChange(ev) {
        const value = ev.target.value ? Number(ev.target.value) : null;
        this.pnmState.displayCurrencyId = value;
        try {
            if (value) {
                localStorage.setItem(DISPLAY_CURRENCY_STORAGE_KEY, String(value));
            } else {
                localStorage.removeItem(DISPLAY_CURRENCY_STORAGE_KEY);
            }
        } catch {
            // Best-effort only - a private/locked-down browser just won't
            // remember the choice across reloads.
        }
        this.model.load({
            context: { ...this.model.config.context, display_currency_id: value || undefined },
        });
    }
}

export const pnmPartNumberListView = {
    ...jaconCoreListView,
    Controller: PnmPartNumberListController,
    buttonTemplate: "part_number_manager.PartNumberList.Buttons",
};

registry.category("views").add("pnm_part_number_list", pnmPartNumberListView);
