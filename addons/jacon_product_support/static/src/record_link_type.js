import { recordLinkTypes } from "@jacon_core/html_record_link/record_link_dialog";
import { _t } from "@web/core/l10n/translation";

recordLinkTypes.add("product_support", {
    label: _t("Product Support"),
    prefix: _t("PS"),
    resModel: "product.support.request",
    actionPath: "product-support",
    numberField: "name",
    titleField: "title",
}, { sequence: 30 });
