{
    'name': 'Jacon Core',
    'version': '19.0.1.1.0',
    'category': 'Hidden/Tools',
    'summary': 'Shared, cross-cutting extensions used by multiple Jacon addons',
    'description': """
Jacon Core
==========
A standing home for small, cross-cutting model extensions shared across
Jacon's addons - thin `_inherit`s on models this addon does not own
(e.g. `project.task`), not a distinct business domain of its own.

Distinct business domains (even if also reusable) should still get their
own addon; only generic field/behavior extensions belong here.

Currently provides:
- Task Type: a fixed classification (3D, 2D, Sch, BOM, ...) on every Task, usable in Timesheet reporting to break down time spent per discipline.
- Clipboard Image field widget: an Image field variant that accepts a picture pasted straight from the clipboard (Ctrl+V), for use on any Image field of any addon.
- Evidence: proof-of-completion file attachments on any Task (moved here from engineering_change, which originally restricted it to its own tasks).
- Project Model: exposes equipment_model's `project.project.model_id` on the Project form and quick-create dialog.
- Equipment Serials: Machine Serial, Engine Serial, VIN/TIN free-text fields on the Project form, next to the Model field.
- Project Events: a "Project Events" tab on the Project form (PO Received Date, IOF/BOM/Drawing Release, QC Checksheet, Photo Taken + Note).
- Date-or-N/A field widget: a Date field variant that shows "N/A" instead of blank when unset.
- Day-month date field widget: a Date field variant that always shows "5 Aug, 2026" (fixed day-before-month) instead of the browser locale's default order or relative wording ("Tomorrow", "In 26 days") - used on the Task Deadline (Kanban card).
- Resizable column memory: every list view (in any module that depends on jacon_core) remembers column widths the user drags, across browser refreshes.
- Left-aligned number columns: the Project and Task List views left-align numeric columns and use a darker zebra striping.
- Edit lock: existing Projects open read-only; an "Edit" button prompts for the current user's own password before unlocking the form, and it re-locks after every save/reload. New (unsaved) Projects are always fully editable.
- Form layout: system-wide, widens the form sheet and gives the chatter side panel a narrower fixed width, so more of the form is visible without shrinking the chatter down to unreadable. Adds a handle to collapse/expand the chatter on demand.
- Start Date: an explicit, editable Task field (defaults to the creation date) alongside Deadline - the window an engineer's remaining hours on that task are spread across.
- Overload warning: assigning a Task (Engineer, Allocated Hours, Start Date, Deadline) warns right on the form if it would push that engineer's combined daily workload over their working-calendar capacity on any day between Start Date and Deadline, and links to a review wizard listing the other tasks contributing to it - each row's New Deadline opens pre-filled with the nearest date that engineer has room, editable before anything is actually saved to the tasks.
- Schedule change request: a Task's assignee cannot edit Start Date/Deadline/Allocated Hours directly - only propose new values (with a reason) instead; their direct HR manager (Employee > Manager) sees an Approve/Reject banner on the task and is the only one who can apply it. Assigning a Task also notifies the assignee's manager.
""",
    'author': 'Jacon',
    'license': 'LGPL-3',
    'depends': ['base', 'project', 'hr_timesheet', 'equipment_model'],
    'data': [
        'security/ir.model.access.csv',
        'views/project_task_views.xml',
        'views/hr_timesheet_views.xml',
        'views/project_project_views.xml',
        'wizard/delete_password_wizard_views.xml',
        'wizard/task_deadline_wizard_views.xml',
        'wizard/task_propose_deadline_wizard_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'jacon_core/static/src/fields/clipboard_image_field.js',
            'jacon_core/static/src/fields/date_or_na_field.js',
            'jacon_core/static/src/fields/date_or_na_field.xml',
            'jacon_core/static/src/fields/day_month_date_field.js',
            'jacon_core/static/src/fields/task_title_autocomplete_field.js',
            'jacon_core/static/src/fields/task_title_autocomplete_field.xml',
            'jacon_core/static/src/list/resizable_column_list_view.js',
            'jacon_core/static/src/list/left_align_number_list_view.js',
            'jacon_core/static/src/list/left_align_number_list_view.scss',
            'jacon_core/static/src/list/task_deadline_badge.scss',
            'jacon_core/static/src/project_lock/project_unlock_dialog.js',
            'jacon_core/static/src/project_lock/project_unlock_dialog.xml',
            'jacon_core/static/src/project_lock/project_edit_lock_field.js',
            'jacon_core/static/src/project_lock/project_edit_lock_field.xml',
            'jacon_core/static/src/project_lock/project_field_readonly_patch.js',
            'jacon_core/static/src/project_lock/project_relock_on_save_patch.js',
            'jacon_core/static/src/chatter/chatter_collapse_toggle.js',
            'jacon_core/static/src/project_stage_confirm/project_stage_confirm.js',
            'jacon_core/static/src/scss/form_layout.scss',
        ],
    },
    'installable': True,
    'application': False,
}
