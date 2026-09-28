{
    'name': 'Jacon Certificate',
    'version': '19.0.1.0.0',
    'category': 'Productivity',
    'summary': 'Free-depth reference tree for certificates/standards lookup',
    'description': """
Jacon Certificate
==================
A free-depth reference tree for certificates/standards lookup
(e.g. Certificates > Trailers > AU > S30 - Certificate #...), each node
carrying a rich-text description. Browsable through a dedicated tree
explorer.

Moved out of Equipment Model into its own addon under the "Documents" app,
since it is not tied to any Equipment Model data.
""",
    'author': 'Jacon',
    'license': 'LGPL-3',
    'depends': ['base', 'jacon_documents', 'web_hierarchy'],
    'data': [
        'security/certificate_groups.xml',
        'security/ir.model.access.csv',
        'views/equipment_certificate_views.xml',
        'views/certificate_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'jacon_certificate/static/src/certificate_explorer/certificate_explorer.js',
            'jacon_certificate/static/src/certificate_explorer/certificate_explorer.xml',
            'jacon_certificate/static/src/certificate_explorer/certificate_explorer.scss',
        ],
    },
    'installable': True,
    'application': False,
    'pre_init_hook': 'pre_init_hook',
}
