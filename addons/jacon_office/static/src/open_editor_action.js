import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";

// Opens the document editor in a new browser tab, then closes the dialog that
// asked for it (which also refreshes the form behind it). A plain URL action
// would leave the dialog open. A browser may refuse a tab opened this late: then
// the user is told, with a button to open it.
registry.category("actions").add("jacon_office_open_editor", (env, action) => {
    const url = action.params.url;
    if (!browser.open(url, "_blank")) {
        env.services.notification.add(_t("Your browser blocked the editor's tab."), {
            type: "warning",
            sticky: true,
            buttons: [{ name: _t("Open the editor"), primary: true, onClick: () => browser.open(url, "_blank") }],
        });
    }
    return { type: "ir.actions.act_window_close" };
});
