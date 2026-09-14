/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { titleService } from "@web/core/browser/title_service";

// web's own title_service.js falls back to the literal string "Odoo" for
// the browser tab title whenever no title parts are set (e.g. on the
// Settings/Apps list screens) - there's no config option for this, so the
// only way to rebrand it is to post-process document.title after every
// update. setParts/setCounters are the only two entry points that ever
// change the title, and both call the service's private updateTitle()
// synchronously before returning - wrapping them and fixing up
// document.title right after covers every case.
const originalStart = titleService.start.bind(titleService);

patch(titleService, {
    start(env, deps) {
        const original = originalStart(env, deps);
        const rebrand = () => {
            document.title = document.title.replace(/\bOdoo\b/g, "JaconS");
        };
        return {
            get current() {
                return original.current;
            },
            getParts: original.getParts,
            setCounters(...args) {
                original.setCounters(...args);
                rebrand();
            },
            setParts(...args) {
                original.setParts(...args);
                rebrand();
            },
        };
    },
});
