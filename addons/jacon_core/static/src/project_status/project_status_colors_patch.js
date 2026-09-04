import { STATUS_COLORS } from "@project/utils/project_utils";

// Client-side counterpart to STATUS_COLOR.update(...) in
// models/project_project.py - the project_state_selection widget (and the
// status_with_color one on the Project form) render each dropdown option's
// bubble color from this plain object, imported by reference, before
// anything is saved - so 'cancelled'/'eol' need an entry here too, or the
// popup would show them with no color at all until picked. Values must
// stay in sync with STATUS_COLOR in project_project.py.
Object.assign(STATUS_COLORS, {
    in_progress: 20, // green - matches core's old 'on_track' color
    cancelled: 1, // red (standard Kanban tag color, index 1)
    eol: 5, // purple (standard Kanban tag color, index 5)
});
