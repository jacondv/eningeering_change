import { onMounted, onPatched, useRef } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { FormRenderer } from "@web/views/form/form_renderer";

// Adds a small handle between the sheet and the side chatter (see
// form_layout.scss for the widened chatter) to collapse it out of the way
// and reopen it later - inserted imperatively since the chatter itself is
// compiled dynamically by mail's own form_compiler.js, not a static
// template we can t-inherit.
patch(FormRenderer.prototype, {
    setup() {
        super.setup();
        // Same ref name core's own setup() attaches via t-ref="compiled_view_root" -
        // FormRenderer has no built-in `this.el`, only exposes it through this ref.
        this.chatterToggleRootRef = useRef("compiled_view_root");
        onMounted(() => this.setupChatterCollapseToggle());
        onPatched(() => this.setupChatterCollapseToggle());
    },
    setupChatterCollapseToggle() {
        const chatter = this.chatterToggleRootRef.el?.querySelector(".o-mail-Form-chatter.o-aside");
        if (!chatter) {
            return;
        }
        const parent = chatter.parentElement;
        if (!parent || parent.querySelector(":scope > .o_chatter_collapse_toggle")) {
            return;
        }
        const toggle = document.createElement("div");
        toggle.className = "o_chatter_collapse_toggle";
        toggle.title = "Collapse/expand chatter";
        toggle.innerHTML = '<i class="fa fa-angle-right"/>';
        toggle.addEventListener("click", () => {
            const collapsed = chatter.classList.toggle("o_chatter_collapsed");
            toggle.querySelector("i").className = collapsed ? "fa fa-angle-left" : "fa fa-angle-right";
        });
        parent.insertBefore(toggle, chatter);
    },
});
