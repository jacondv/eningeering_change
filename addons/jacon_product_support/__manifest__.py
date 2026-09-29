{
    'name': 'Product Support',
    'version': '19.0.1.0.0',
    'category': 'Services',
    'summary': 'Log support, diagnosis and guidance given to customers for machine faults',
    'description': """
Product Support
===============
Records every support case raised by a customer about one of our machines
(identified by its Job Number): the fault, the diagnosis, the actions taken
and the solution given - see docs/Product_Support_TechSpec.md.
""",
    'author': 'Jacon',
    'license': 'LGPL-3',
    'depends': [
        'mail', 'project', 'hr_timesheet',
        'jacon_core', 'equipment_model', 'jacon_customer_site', 'engineering_change',
    ],
    'data': [
        'security/product_support_groups.xml',
        'security/ir.model.access.csv',
        'data/product_support_data.xml',
        'views/product_support_request_views.xml',
        'views/product_support_fault_category_views.xml',
        'views/product_support_dashboard_views.xml',
        'views/project_project_views.xml',
        'views/engineering_change_views.xml',
        'views/product_support_menus.xml',
        'report/product_support_report.xml',
        'report/product_support_report_templates.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'jacon_product_support/static/src/**/*',
        ],
    },
    'installable': True,
    'application': True,
    'post_init_hook': 'post_init_hook',
}
