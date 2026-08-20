{
    'name': 'Jacon Project Dashboard',
    'version': '19.0.1.0.0',
    'category': 'Project',
    'summary': 'Planning vs Spending hours analytics across Projects, Task Types, and Engineers',
    'description': """
Jacon Project Dashboard
========================
A filterable analytics dashboard answering "how much engineering time is
going where" - broken down by Project, Task Type (2D/3D/BOM/FEM/...),
Engineer, and time period, comparing planned (Allocated Time) against
actually spent (Timesheet) hours.

Restricted to Project Administrators (project.group_project_manager).
""",
    'author': 'Jacon',
    'license': 'LGPL-3',
    'depends': ['base', 'project', 'hr_timesheet', 'jacon_core'],
    'data': [
        'security/ir.model.access.csv',
        'views/jacon_project_dashboard_actions.xml',
        'views/jacon_project_dashboard_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'jacon_project_dashboard/static/src/dashboard/jacon_project_dashboard.js',
            'jacon_project_dashboard/static/src/dashboard/jacon_project_dashboard.xml',
            'jacon_project_dashboard/static/src/dashboard/jacon_project_dashboard.scss',
        ],
        # Vendored Frappe Gantt (MIT, see static/lib/frappe_gantt/LICENSE.txt),
        # lazy-loaded via loadBundle like web.chartjs_lib - only the Task
        # Timeline panel needs it, no point shipping it in every backend page.
        'jacon_project_dashboard.frappe_gantt_lib': [
            'jacon_project_dashboard/static/lib/frappe_gantt/frappe-gantt.umd.js',
            'jacon_project_dashboard/static/lib/frappe_gantt/frappe-gantt.css',
        ],
    },
    'installable': True,
    'application': False,
}
