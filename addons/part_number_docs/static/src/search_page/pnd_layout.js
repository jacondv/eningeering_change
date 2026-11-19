/** @odoo-module **/

import { useState } from "@odoo/owl";

const MIN_SPLIT = 25;
const MAX_SPLIT = 75;

/**
 * What a user arranged on a custom page - the share of the left side, the width of the columns, the
 * columns that are hidden - kept in this browser, per page (`key`), and given back the next time.
 * Usable by any custom page.
 *
 *   const layout = useLayoutPrefs("my_page", { splitPct: 58 });
 *   layout.state.splitPct / .widths / .hidden ; layout.save() ; layout.reset()
 */
export function useLayoutPrefs(key, defaults = {}) {
    const storageKey = `jacon_layout:${key}`;
    const defaultSplit = defaults.splitPct || 58;
    const state = useState({ splitPct: defaultSplit, widths: {}, hidden: [] });

    try {
        const saved = JSON.parse(localStorage.getItem(storageKey)) || {};
        if (typeof saved.splitPct === "number") {
            state.splitPct = Math.min(Math.max(saved.splitPct, MIN_SPLIT), MAX_SPLIT);
        }
        for (const [column, width] of Object.entries(saved.widths || {})) {
            if (typeof width === "number" && width > 0) {
                state.widths[column] = width;
            }
        }
        if (Array.isArray(saved.hidden)) {
            state.hidden = saved.hidden.filter((column) => typeof column === "string");
        }
    } catch {
        // no storage, or a damaged value: the defaults
    }

    return {
        state,
        MIN_SPLIT,
        MAX_SPLIT,
        save() {
            try {
                localStorage.setItem(
                    storageKey,
                    JSON.stringify({ splitPct: state.splitPct, widths: state.widths, hidden: state.hidden })
                );
            } catch {
                // the layout is just not remembered
            }
        },
        reset() {
            state.splitPct = defaultSplit;
            state.widths = {};
            state.hidden = [];
            try {
                localStorage.removeItem(storageKey);
            } catch {
                // nothing to forget
            }
        },
    };
}

/**
 * Follows the mouse after a press until it is released: onMove(dx, dy) from the press point, then
 * onEnd(). The page is covered while dragging so that a PDF frame does not swallow the mouse.
 */
export function dragFrom(startEvent, onMove, onEnd) {
    startEvent.preventDefault();
    const startX = startEvent.clientX;
    const startY = startEvent.clientY;
    const move = (ev) => onMove(ev.clientX - startX, ev.clientY - startY, ev);
    const stop = () => {
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", stop);
        window.removeEventListener("pointercancel", stop);
        onEnd();
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop);
    window.addEventListener("pointercancel", stop);
}
