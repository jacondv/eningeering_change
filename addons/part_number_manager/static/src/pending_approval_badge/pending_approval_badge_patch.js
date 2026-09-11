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
        return sections.map((section) => this._pnmApplyPendingApprovalBadge(section));
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
