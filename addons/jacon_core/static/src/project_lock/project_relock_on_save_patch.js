import { patch } from "@web/core/utils/patch";
import { Record } from "@web/model/relational_model/record";

// Belt-and-braces re-lock: the server already recomputes is_unlocked back to
// False on every fresh read (see models/project_project.py), and a save
// normally reloads the record anyway - but force it back to False here too,
// scoped to project.project only, so the form is guaranteed to lock
// immediately on Save even if some save path skips the reload.
patch(Record.prototype, {
    async _save(options) {
        const result = await super._save(options);
        if (result && this.resModel === "project.project" && "is_unlocked" in this.data) {
            this.data.is_unlocked = false;
        }
        return result;
    },
});
