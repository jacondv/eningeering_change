/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { NavBar } from "@web/webclient/navbar/navbar";
import { onWillDestroy, onWillStart, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

// Odoo's sidebar/top-nav menu items have no built-in counter badge (unlike
// Discuss's inbox) - stamping a `pnmPendingCount` property onto the matching
// menu node here, then rendering it as a small red badge via the template
// patches in pending_approval_badge_patch.xml, covers every place that tree
// gets rendered (top nav dropdown, small-screen app sidebar, "more" overflow
// dropdown - all share this same tree/templates).
const PENDING_APPROVAL_XMLID = "part_number_manager.menu_pnm_pending_approval";

patch(NavBar.prototype, {
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.pnmPendingApprovalState = useState({ count: 0 });
        const refreshCount = async () => {
            this.pnmPendingApprovalState.count = await this.orm.searchCount(
                "part_number_manager.part_number", [["approval_state", "=", "pending"]]
            );
        };
        onWillStart(refreshCount);
        // Re-fetch whenever the current view/action re-renders (e.g. right
        // after the Approve/Reject confirm wizard closes and the Pending
        // Approval list reloads its rows) - not a live/pushed counter, but
        // the count no longer stays stale for the rest of the session
        // after it reaches 0.
        this.env.bus.addEventListener("ACTION_MANAGER:UI-UPDATED", refreshCount);
        onWillDestroy(() => {
            this.env.bus.removeEventListener("ACTION_MANAGER:UI-UPDATED", refreshCount);
        });
    },

    get currentAppSections() {
        const sections = super.currentAppSections;
        if (!this.pnmPendingApprovalState.count) {
            return sections;
        }
        // Memoized on (sections reference, count) - `currentAppSections` is
        // a getter Owl re-evaluates on every render of the whole NavBar
        // (not just when the menu tree or the count actually changes), and
        // without this, every single call below would rebuild a BRAND NEW
        // object graph (new "Tasks" section, new childrenTree array) even
        // when nothing changed. Odoo's own SectionsMenu dropdown template
        // (My Tasks/All Tasks etc.) then sees a "new" tree on every render
        // while a popover happens to be open, and Owl's reconciliation can
        // end up leaving the old DOM nodes behind alongside the new ones -
        // duplicated menu rows, and since this patch runs for every app
        // (not just Part Number), it affected every dropdown in the NavBar.
        // Reusing the exact same result object across renders (as long as
        // the underlying sections and the count haven't changed) keeps
        // object identity stable and avoids that glitch.
        if (this._pnmBadgeCache && this._pnmBadgeCache.sections === sections &&
            this._pnmBadgeCache.count === this.pnmPendingApprovalState.count) {
            return this._pnmBadgeCache.result;
        }
        const result = sections.map((section) => this._pnmApplyPendingApprovalBadge(section));
        this._pnmBadgeCache = { sections, count: this.pnmPendingApprovalState.count, result };
        return result;
    },

    _pnmApplyPendingApprovalBadge(section) {
        if (section.xmlid === PENDING_APPROVAL_XMLID) {
            return { ...section, pnmPendingCount: this.pnmPendingApprovalState.count };
        }
        if (section.childrenTree && section.childrenTree.length) {
            return {
                ...section,
                childrenTree: section.childrenTree.map((c) => this._pnmApplyPendingApprovalBadge(c)),
            };
        }
        return section;
    },
});
