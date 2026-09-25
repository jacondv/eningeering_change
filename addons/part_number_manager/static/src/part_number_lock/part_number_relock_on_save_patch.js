import { patch } from "@web/core/utils/patch";
import { Record } from "@web/model/relational_model/record";

// Left as a no-op: whether an existing Part Number re-locks after Save now
// depends on Settings > General Settings > Part Numbers > "Require password
// to edit Part Numbers" (see _compute_is_unlocked on models/part_number.py)
// - forcing it to False here unconditionally would wrongly re-lock the form
// even while that setting is off. The server-side compute + the normal
// field reload a save already does is enough on its own (this patch was
// only ever a defensive extra for a save path that skips the reload - not
// worth resurrecting just for that one edge case now that the source of
// truth is a runtime setting, not a constant).
patch(Record.prototype, {
    async _save(options) {
        return super._save(options);
    },
});
