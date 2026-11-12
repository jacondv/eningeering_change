import { recordLinkTypes } from "@jacon_core/html_record_link/record_link_dialog";
import { _t } from "@web/core/l10n/translation";

recordLinkTypes.add("office_document", {
    label: _t("Document"),
    prefix: _t("Doc"),
    resModel: "jacon.office.document",
    actionPath: "office-documents",
    titleField: "name",
}, { sequence: 60 });
