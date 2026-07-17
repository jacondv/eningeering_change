{
    'name': 'Inventor Connector',
    'version': '19.0.1.0.0',
    'category': 'Manufacturing',
    'summary': 'Generic REST endpoint to receive BOM data pushed from Autodesk Inventor',
    'description': """
Inventor Connector
===================
Generic, business-agnostic layer that receives Bill of Materials (BOM) data
pushed from Autodesk Inventor (via script/add-in) over a REST API and stores
it in Odoo.

This module deliberately knows nothing about what any BOM's lines look like -
each business module that wants to consume a given BOM type (e.g.
qc_checksheet for "panel_sticker") registers its own line model against a
`bom_type` key in `inventor.bom.type`, and defines what to do with the data.
""",
    'author': 'Jacon',
    'license': 'LGPL-3',
    'depends': ['base'],
    'data': [
        'security/inventor_connector_groups.xml',
        'security/ir.model.access.csv',
        'data/ir_config_parameter.xml',
        'views/inventor_bom_views.xml',
        'views/res_config_settings_views.xml',
        'views/inventor_connector_menus.xml',
    ],
    'installable': True,
    'application': False,
}
