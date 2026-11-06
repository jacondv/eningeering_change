{
    'name': 'QC Check Sheet',
    'version': '19.0.1.7.0',
    'category': 'Manufacturing/Quality',
    'summary': 'Author QC check sheets on Odoo and print them to the standard paper form',
    'description': """
QC Check Sheet
==============
Replaces the Word-based QC check sheet with: author content on Odoo -> export a
PDF that matches the original paper form -> print -> technician checks by hand.

Features:
- Check sheet content is authored from scratch or copied from another Job's Released check sheet
- Draft > In Review > Released workflow with one approval level, Recall and Reject
- Released content is locked; any change needs a New Revision, and old Revisions stay viewable and printable
- Standard type: Inspection Groups containing Items, written on a dedicated full-page editor; Tested/OK-NOK always printed blank
- Panel & Sticker type: Panel Lines entered entirely by hand (Part Number, Description, Image, Qty, Note)
- PDF report matching the original paper layout
""",
    'author': 'Jacon',
    'license': 'LGPL-3',
    'depends': ['base', 'mail', 'web', 'html_editor', 'project', 'equipment_model', 'jacon_core', 'inventor_connector', 'jacon_documents'],
    'data': [
        'security/qc_checksheet_groups.xml',
        'security/ir.model.access.csv',
        'data/inventor_bom_type_data.xml',
        'data/qc_checksheet_type_data.xml',
        'data/qc_checksheet_config_data.xml',
        'wizard/qc_checksheet_copy_wizard_views.xml',
        'wizard/qc_checksheet_inventor_import_wizard_views.xml',
        'wizard/qc_checksheet_new_revision_wizard_views.xml',
        'wizard/qc_checksheet_reject_wizard_views.xml',
        'wizard/qc_checksheet_settings_views.xml',
        'report/qc_checksheet_report.xml',
        'report/qc_checksheet_report_templates.xml',
        'views/qc_checksheet_editor_actions.xml',
        'views/qc_checksheet_views.xml',
        'views/qc_checksheet_dashboard_views.xml',
        'views/qc_checksheet_type_views.xml',
        'views/project_project_views.xml',
        'views/qc_checksheet_menus.xml',
        'views/inventor_bom_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'qc_checksheet/static/src/css/qc_checksheet.css',
            'qc_checksheet/static/src/editor/*.js',
            'qc_checksheet/static/src/editor/*.xml',
            'qc_checksheet/static/src/editor/*.scss',
            'qc_checksheet/static/src/job/*.js',
            'qc_checksheet/static/src/job/*.xml',
            'qc_checksheet/static/src/job/*.scss',
            'qc_checksheet/static/src/dashboard/*.js',
            'qc_checksheet/static/src/dashboard/*.xml',
            'qc_checksheet/static/src/dashboard/*.scss',
        ],
    },
    'installable': True,
    'application': False,
    'post_init_hook': 'post_init_hook',
}
