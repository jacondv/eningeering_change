{
    'name': 'Jacon Core',
    'version': '19.0.1.0.0',
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
- Project Events: a "Project Events" tab on the Project form (PO Received Date, IOF/BOM/Drawing Release, QC Checksheet, Photo Taken + Note).
- Date-or-N/A field widget: a Date field variant that shows "N/A" instead of blank when unset.
""",
    'author': 'Jacon',
    'license': 'LGPL-3',
    'depends': ['base', 'project', 'hr_timesheet', 'equipment_model'],
    'data': [
        'security/ir.model.access.csv',
        'views/project_task_views.xml',
        'views/hr_timesheet_views.xml',
        'views/project_project_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'jacon_core/static/src/fields/clipboard_image_field.js',
            'jacon_core/static/src/fields/date_or_na_field.js',
            'jacon_core/static/src/fields/date_or_na_field.xml',
        ],
    },
    'installable': True,
    'application': False,
}
