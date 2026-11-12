{
    'name': 'Office Documents - Project',
    'version': '19.0.1.0.0',
    'category': 'Productivity',
    'summary': 'A Documents tab on the Project form',
    'description': """
Office Documents - Project
==========================
Glue between `jacon_office` and Projects: makes a Project own Office Documents
and shows them in a Documents tab on its form. Installed automatically when
both are present; removing it only removes the tab.
""",
    'author': 'Jacon',
    'license': 'LGPL-3',
    'depends': ['jacon_office', 'project'],
    'data': [
        'views/project_project_views.xml',
    ],
    'auto_install': True,
    'installable': True,
    'application': False,
}
