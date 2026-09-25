import { patch } from "@web/core/utils/patch";
import { Record } from "@web/model/relational_model/record";

// TEMPORARY: Edit-lock/password feature disabled (see _compute_is_unlocked
// on models/part_number.py, which now always computes True) - this patch's
// forced re-lock-after-save would otherwise fight that and leave the form
// briefly readonly again until the next reload, so it's a no-op for now.
// To restore: revert models/part_number.py first, then uncomment the body
// below.
patch(Record.prototype, {
    async _save(options) {
        const result = await super._save(options);
        // if (result && this.resModel === "part_number_manager.part_number" && "is_unlocked" in this.data) {
        //     this.data.is_unlocked = false;
        // }
        return result;
    },
});
