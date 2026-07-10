{
    'name': 'Engineering Change / DCR Management',
    'version': '19.0.1.0.0',
    'category': 'Manufacturing/Quality',
    'summary': 'Manage Engineering Change Requests (Minor Change & DCR)',
    'description': """
Engineering Change / DCR Management
====================================
Digitizes the full lifecycle of an Engineering Change Request:
proposal -> risk assessment -> approval -> implementation -> evidence closure.

Features:
- Minor Change and DCR (Design Change Request) request types
- Two-level approval workflow: Manager -> BOD (for DCR)
- Risk assessment (RPN) with impact fields
- Implementation actions/tasks with evidence upload
- Followers & automatic email notifications
- Overdue action reminders via scheduled action
- PDF report
""",
    'author': 'DCR Project',
    'license': 'LGPL-3',
    'depends': ['base', 'mail', 'web', 'project'],
    'data': [
        'security/engineering_change_groups.xml',
        'security/engineering_change_rules.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'data/mail_template_data.xml',
        'data/ir_cron_data.xml',
        'wizard/engineering_change_reject_wizard_views.xml',
        'views/engineering_change_views.xml',
        'views/engineering_change_action_views.xml',
        'views/engineering_change_action_evidence_views.xml',
        'views/engineering_change_dashboard_views.xml',
        'views/engineering_change_menus.xml',
        'report/engineering_change_report.xml',
        'report/engineering_change_report_templates.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'engineering_change/static/src/scss/engineering_change.scss',
            'engineering_change/static/src/dashboard/engineering_change_dashboard.scss',
            'engineering_change/static/src/dashboard/engineering_change_dashboard.js',
            'engineering_change/static/src/dashboard/engineering_change_dashboard.xml',
        ],
    },
    'installable': True,
    'application': True,
    'post_init_hook': 'post_init_hook',
}
