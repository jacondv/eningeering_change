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
- Templates hold only branding (logo/company) and a default Approval seed list
- Check sheet content is authored from scratch or copied from a previous check sheet
- Standard type: Inspection Groups containing Items, Tested/OK-NOK always printed blank
- Panel & Sticker type: Panel Lines looked up against product.product, with manual image override and bulk Excel import
- PDF report matching the original paper layout
""",
    'author': 'Jacon',
    'license': 'LGPL-3',
    'depends': ['base', 'web', 'project', 'product'],
    'data': [
        'security/qc_checksheet_groups.xml',
        'security/ir.model.access.csv',
        'wizard/qc_checksheet_copy_wizard_views.xml',
        'wizard/qc_checksheet_import_wizard_views.xml',
        'report/qc_checksheet_report.xml',
        'report/qc_checksheet_report_templates.xml',
        'views/qc_checksheet_template_views.xml',
        'views/qc_checksheet_views.xml',
        'views/qc_checksheet_menus.xml',
    ],
    'installable': True,
    'application': True,
    'post_init_hook': 'post_init_hook',
}
