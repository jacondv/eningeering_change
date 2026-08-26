{
    'name': 'Hose And Fitting Manager',
    'version': '19.0.1.0.0',
    'category': 'Manufacturing',
    'summary': 'Configure and quickly build Hose and Fitting assemblies per Job, on top of Part Number Manager',
    'description': """
Hose And Fitting Manager
=========================
Adds a "Hose And Fitting Config" (per Hose Symbol) reference and a
dedicated Builder page for quickly listing the hose assemblies needed on
a Job - every Hose/Fitting/Ferrule/Fire Wrap always resolves to a real
part_number_manager.part_number record.

Depends on part_number_manager; does not modify its models beyond the
already-shared `display_description` field.
""",
    'author': 'Jacon',
    'license': 'LGPL-3',
    'depends': ['part_number_manager'],
    'data': [
        'security/ir.model.access.csv',
        'views/config_views.xml',
        'views/job_hose_line_views.xml',
        'views/builder_actions.xml',
        'views/menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'hose_fitting_manager/static/src/builder/builder.scss',
            'hose_fitting_manager/static/src/builder/builder.js',
            'hose_fitting_manager/static/src/builder/builder.xml',
            'hose_fitting_manager/static/src/list_display_combobox/pnm_display_many2one_field.js',
            'hose_fitting_manager/static/src/list_display_combobox/pnm_display_many2one_field.xml',
        ],
    },
    'installable': True,
    'application': False,
}
