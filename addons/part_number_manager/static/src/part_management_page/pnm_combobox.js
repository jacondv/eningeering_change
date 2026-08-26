/** @odoo-module **/

import { Component, useEffect, useRef, useState } from "@odoo/owl";

// A self-contained, self-drawn dropdown (never the browser's native
// <datalist> suggestion popup - see part_management_page.js for why: Chrome
// stops showing datalist suggestions the moment a controlled input
// re-assigns .value on every keystroke, which paste-cascading and Save
// validation both need to do here). Typing filters `options` by substring;
// clicking one selects it. `allowCreate=false` (Material Group/Job Number/
// Part Type/Target Part) rejects any text that isn't an exact match to an
// existing option - it's cleared back out on blur rather than left sitting
// in the box looking "accepted". `allowCreate=true` (Vendor/Old Part
// Number) leaves unmatched text in place instead, for the caller to create
// on Save.
export class PnmCombobox extends Component {
    static template = "part_number_manager.PnmCombobox";
    static props = {
        options: Array, // [{id, label}]
        text: String,
        value: [Number, Boolean],
        placeholder: { type: String, optional: true },
        disabled: { type: Boolean, optional: true },
        allowCreate: { type: Boolean, optional: true },
        externalFilter: { type: Boolean, optional: true }, // caller already filtered `options` - skip our own text filter
        onInput: Function, // (text) => void
        onSelect: Function, // (option) => void
        onPaste: { type: Function, optional: true }, // (ev) => void
        onBlurExtra: { type: Function, optional: true }, // () => void - runs after this component's own blur handling
        onFocusExtra: { type: Function, optional: true }, // () => void - runs after this component's own focus handling (e.g. to load options on click, not just on keystroke)
    };
    static defaultProps = {
        placeholder: "Type to search...",
        disabled: false,
        allowCreate: false,
        externalFilter: false,
    };

    setup() {
        // highlightIndex tracks the arrow-key-hovered row in the dropdown -
        // separate from props.value (the actually *selected* option), same
        // split Odoo's own Many2one AutoComplete widget makes.
        this.state = useState({ open: false, highlightIndex: -1 });
        this.inputRef = useRef("input");
        this.menuRef = useRef("menu");

        // Keeps the arrow-key-highlighted row scrolled into view, same as
        // Odoo's own Many2one AutoComplete dropdown.
        useEffect(
            () => {
                this.menuRef.el
                    ?.querySelector(".o_pnm_combobox_option.highlighted")
                    ?.scrollIntoView({ block: "nearest" });
            },
            () => [this.state.highlightIndex, this.state.open]
        );
    }

    get filteredOptions() {
        if (this.props.externalFilter) {
            // Caller already computed the exact set to show (e.g. a
            // numeric-tolerance filter, not a text substring match) -
            // filtering again by `text` here would incorrectly hide valid
            // options whose label doesn't literally contain what was typed.
            return this.props.options.slice(0, 50);
        }
        const norm = (this.props.text || "").trim().toLowerCase();
        let options = this.props.options;
        if (norm) {
            options = options.filter((o) => o.label.toLowerCase().includes(norm));
        }
        return options.slice(0, 50);
    }

    onFocus() {
        this.state.open = true;
        this.state.highlightIndex = -1;
        this.props.onFocusExtra?.();
    }

    onInput(ev) {
        this.props.onInput(ev.target.value);
        this.state.open = true;
        this.state.highlightIndex = -1;
    }

    onPaste(ev) {
        this.props.onPaste?.(ev);
    }

    onBlur() {
        this.state.open = false;
        // A mousedown-selected option already ran onSelect before this
        // fires (mousedown precedes blur) - this only ever has to discard
        // leftover text that never matched anything.
        if (!this.props.allowCreate && !this.props.value && this.props.text) {
            this.props.onInput("");
        }
        this.props.onBlurExtra?.();
    }

    _selectOption(opt) {
        this.props.onSelect(opt);
        this.state.open = false;
        this.state.highlightIndex = -1;
    }

    onOptionMouseDown(opt) {
        this._selectOption(opt);
    }

    onOptionMouseEnter(index) {
        this.state.highlightIndex = index;
    }

    onToggle() {
        this.state.open = !this.state.open;
        if (this.state.open) {
            this.inputRef.el?.focus();
        }
    }

    onClear() {
        this.props.onInput("");
        this.inputRef.el?.focus();
    }

    // Same keyboard behavior as Odoo's own Many2one AutoComplete: Up/Down
    // moves a highlight through the currently filtered list (opening it if
    // needed), Enter picks whatever's highlighted, Escape closes without
    // picking anything.
    onKeydown(ev) {
        const options = this.filteredOptions;
        switch (ev.key) {
            case "ArrowDown": {
                ev.preventDefault();
                if (!this.state.open) {
                    this.state.open = true;
                }
                if (options.length) {
                    this.state.highlightIndex = (this.state.highlightIndex + 1) % options.length;
                }
                break;
            }
            case "ArrowUp": {
                ev.preventDefault();
                if (!this.state.open) {
                    this.state.open = true;
                }
                if (options.length) {
                    this.state.highlightIndex =
                        (this.state.highlightIndex - 1 + options.length) % options.length;
                }
                break;
            }
            case "Enter": {
                if (this.state.open && this.state.highlightIndex >= 0 && options[this.state.highlightIndex]) {
                    ev.preventDefault();
                    this._selectOption(options[this.state.highlightIndex]);
                }
                break;
            }
            case "Escape": {
                this.state.open = false;
                this.state.highlightIndex = -1;
                this.inputRef.el?.blur();
                break;
            }
        }
    }
}
