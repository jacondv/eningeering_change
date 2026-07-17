{
    'name': 'QC Check Sheet',
    'version': '19.0.1.0.0',
    'category': 'Manufacturing/Quality',
    'summary': 'Author QC check sheets on Odoo and print them to the standard paper form',
    'description': """
QC Check Sheet
==============
Replaces the Word-based QC check sheet with: author content on Odoo -> export a
PDF that matches the original paper form -> print -> technician checks by hand.

Features:
- Check sheet content is authored from scratch or copied from a previous check sheet
- Standard type: Inspection Groups containing Items, Tested/OK-NOK always printed blank
- Panel & Sticker type: Panel Lines entered entirely by hand (Part Number, Description, Image, Qty, Note)
- PDF report matching the original paper layout
""",
    'author': 'Jacon',
    'license': 'LGPL-3',
    'depends': ['base', 'web', 'project'],
    'data': [
        'security/qc_checksheet_groups.xml',
        'security/ir.model.access.csv',
        'wizard/qc_checksheet_copy_wizard_views.xml',
        'report/qc_checksheet_report.xml',
        'report/qc_checksheet_report_templates.xml',
        'views/qc_checksheet_views.xml',
        'views/qc_checksheet_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'qc_checksheet/static/src/css/qc_checksheet.css',
        ],
    },
    'installable': True,
    'application': True,
    'post_init_hook': 'post_init_hook',
}
