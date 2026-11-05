import { HtmlField } from "@html_editor/fields/html_field";
import { patch } from "@web/core/utils/patch";
import { RecordLinkPlugin } from "./record_link_plugin";

patch(HtmlField.prototype, {
    getConfig() {
        const config = super.getConfig(...arguments);
        config.Plugins = [...config.Plugins, RecordLinkPlugin];
        return config;
    },
});
