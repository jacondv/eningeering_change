{
    'name': 'Project Custom Views',
    'version': '19.0.1.0.0',
    'category': 'Services/Project',
    'summary': 'Custom view/UI adjustments for the Project app',
    'description': """
Project Custom Views
=====================
Home for view-layer customizations of the Project app (list/kanban layouts,
custom widgets, etc.) that are not tied to any specific business workflow
(see engineering_change for EC-specific project handling).

Features:
- Indents sub-tasks under their parent in the Tasks list view
""",
    'author': 'DCR Project',
    'license': 'LGPL-3',
    'depends': ['project'],
    'data': [
        'views/project_task_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'project_custom_views/static/src/fields/task_name_indent_field.js',
            'project_custom_views/static/src/fields/task_name_indent_field.xml',
        ],
    },
    'installable': True,
    'application': False,
}
