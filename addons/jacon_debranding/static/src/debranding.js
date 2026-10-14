import { registry } from "@web/core/registry";
import { titleService } from "@web/core/browser/title_service";
import { session } from "@web/session";
// Loaded first so the items below are already registered when removed.
import "@web/webclient/user_menu/user_menu_items";

// Switches set in Settings > General Settings > Debranding, handed over by
// ir.http.session_info (see models/ir_http.py).
const settings = session.jacon_debranding || {};

const userMenuItems = registry.category("user_menuitems");
if (settings.hide_odoo_account) {
    userMenuItems.remove("odoo_account");
}
if (settings.hide_help) {
    userMenuItems.remove("support");
}

// Core's title service falls back to a hard-coded "Odoo" whenever no action
// has set a title yet - swap that fallback (and only it) for our own text.
if (settings.tab_title) {
    const isFallback = (title) => /^(\(\d+\) )?Odoo$/.test(title);
    const replaceFallback = () => {
        if (isFallback(document.title)) {
            document.title = document.title.replace(/Odoo$/, settings.tab_title);
        }
    };
    registry.category("services").add(
        "title",
        {
            ...titleService,
            start(env, deps) {
                const service = titleService.start(env, deps);
                replaceFallback();
                return {
                    ...service,
                    get current() {
                        return service.current;
                    },
                    setParts(parts) {
                        service.setParts(parts);
                        replaceFallback();
                    },
                    setCounters(counters) {
                        service.setCounters(counters);
                        replaceFallback();
                    },
                };
            },
        },
        { force: true }
    );
}
