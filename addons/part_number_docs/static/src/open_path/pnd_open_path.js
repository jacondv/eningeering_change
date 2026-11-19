/** @odoo-module **/

import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";

/**
 * A browser does not open a file of the user's PC from a web page (file:/// links are blocked), but it
 * opens it when the path is pasted in its address bar. So "Open" puts the path on the clipboard and says so.
 */
export async function copyPathToOpen(notification, text) {
    try {
        await navigator.clipboard.writeText(text);
    } catch {
        // Not a secure page (http): the old way.
        const area = document.createElement("textarea");
        area.value = text;
        document.body.appendChild(area);
        area.select();
        document.execCommand("copy");
        area.remove();
    }
    notification.add(_t("Path copied. Press Ctrl+T, Ctrl+V and Enter to open it in a new tab."), {
        title: _t("Open"),
        type: "success",
    });
}

registry.category("actions").add("part_number_docs.open_path", (env, action) =>
    copyPathToOpen(env.services.notification, action.params.text)
);
