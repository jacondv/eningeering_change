/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { NavBar } from "@web/webclient/navbar/navbar";

// Root menus (no parent) belonging to Jacon's own custom addons - these are
// the "apps" shown grouped under the JACON header in the App Switcher.
// Everything else (standard Odoo apps: Discuss, Contacts, Inventory...)
// falls into the "General" group below it.
// Order here is also the display order within the JACON group (see
// jaconApps below) - Project sits above Engineering Change per request.
const JACON_APP_MODULES = [
    "project",
    "engineering_change",
    "part_number_manager",
    "qc_checksheet",
    "equipment_model",
    "inventor_connector",
];

const JACON_APP_ICONS = {
    project: "fa-tasks",
    engineering_change: "fa-refresh",
    part_number_manager: "fa-hashtag",
    qc_checksheet: "fa-check-square-o",
    equipment_model: "fa-cubes",
    inventor_connector: "fa-plug",
};

function moduleOf(app) {
    return (app.xmlid || "").split(".")[0];
}

patch(NavBar.prototype, {
    get jaconApps() {
        return this.menuService
            .getApps()
            .filter((app) => JACON_APP_MODULES.includes(moduleOf(app)))
            .sort((a, b) => JACON_APP_MODULES.indexOf(moduleOf(a)) - JACON_APP_MODULES.indexOf(moduleOf(b)));
    },

    get otherApps() {
        return this.menuService.getApps().filter((app) => !JACON_APP_MODULES.includes(moduleOf(app)));
    },

    getJaconAppIcon(app) {
        return JACON_APP_ICONS[moduleOf(app)] || "fa-th-large";
    },
});
