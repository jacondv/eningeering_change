import { recordLinkTypes } from "@jacon_core/html_record_link/record_link_dialog";
import { _t } from "@web/core/l10n/translation";

recordLinkTypes.add("engineering_change", {
    label: _t("EC"),
    prefix: _t("EC"),
    resModel: "engineering.change",
    actionPath: "engineering-change",
    numberField: "name",
    unassignedNumber: "New",
    titleField: "title",
}, { sequence: 20 });
