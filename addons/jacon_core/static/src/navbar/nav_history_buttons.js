/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { NavBar } from "@web/webclient/navbar/navbar";

// Odoo's SPA navigation already pushes real browser history entries (the
// URL changes as you move between apps/menus/records), so the browser's
// own Back/Forward buttons already work - these just put the same action
// in the header itself, for setups where the browser chrome isn't handy
// (kiosk/PWA windows, or simply so the user doesn't have to reach for it).
patch(NavBar.prototype, {
    onHistoryBack() {
        window.history.back();
    },

    onHistoryForward() {
        window.history.forward();
    },
});
