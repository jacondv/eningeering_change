import { onMounted, onPatched, useRef } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { FormRenderer } from "@web/views/form/form_renderer";

// Adds a small handle between the sheet and the side chatter (see
// form_layout.scss for the widened chatter) to collapse it out of the way
// and reopen it later - inserted imperatively since the chatter itself is
// compiled dynamically by mail's own form_compiler.js, not a static
// template we can t-inherit.
//
// One collapsed/expanded preference is remembered per browser (not per
// record/model) via localStorage - simplest interpretation of "always
// keep it the way I left it", and matches how the Task Timeline's own
// Day/Week/Month choice is persisted elsewhere in this addon.
const CHATTER_COLLAPSED_STORAGE_KEY = "jacon_core.chatter_collapsed";

function loadStoredChatterCollapsed() {
    try {
        return localStorage.getItem(CHATTER_COLLAPSED_STORAGE_KEY) === "1";
    } catch {
        return false;
    }
}

function storeChatterCollapsed(collapsed) {
    try {
        if (collapsed) {
            localStorage.setItem(CHATTER_COLLAPSED_STORAGE_KEY, "1");
        } else {
            localStorage.removeItem(CHATTER_COLLAPSED_STORAGE_KEY);
        }
    } catch {
        // Storage unavailable (private mode, quota, ...) - silently skip.
    }
}

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
        const setIcon = (collapsed) => {
            toggle.innerHTML = `<i class="fa ${collapsed ? "fa-angle-left" : "fa-angle-right"}"/>`;
        };
        // This is a freshly (re)built chatter DOM node (the toggle above
        // was just created since none existed on it yet) - apply last
        // time's remembered state to it right away, before the user has
        // clicked anything on this particular record/view instance.
        const collapsed = loadStoredChatterCollapsed();
        chatter.classList.toggle("o_chatter_collapsed", collapsed);
        setIcon(collapsed);
        toggle.addEventListener("click", () => {
            const nowCollapsed = chatter.classList.toggle("o_chatter_collapsed");
            setIcon(nowCollapsed);
            storeChatterCollapsed(nowCollapsed);
        });
        parent.insertBefore(toggle, chatter);
    },
});
