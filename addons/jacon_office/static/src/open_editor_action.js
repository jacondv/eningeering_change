import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";

// Opens the document editor in a new browser tab, then closes the dialog that
// asked for it (which also refreshes the form behind it). A plain URL action
// would leave the dialog open.
registry.category("actions").add("jacon_office_open_editor", (env, action) => {
    browser.open(action.params.url, "_blank");
    return { type: "ir.actions.act_window_close" };
});
