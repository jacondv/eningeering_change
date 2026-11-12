{
    'name': 'Office Documents',
    'version': '19.0.1.1.0',
    'category': 'Productivity',
    'summary': 'Word, Excel and PowerPoint documents kept on the Odoo server, edited in the browser with ONLYOFFICE and attachable to any record',
    'description': """
Office Documents
================
A reusable document library for Word, Excel and PowerPoint files. A document
belongs to any record (a Project, an Engineering Change, ...) through the
`jacon.office.mixin` mixin; the file itself lives in Odoo's filestore and is
edited in the browser by ONLYOFFICE Docs (via the `onlyoffice_odoo` connector).

This addon knows nothing about Projects, ECs or Product Support: each of those
gets its own tiny, auto-installed glue addon (`jacon_office_project`, ...) that
adds a Documents tab to its form. Uninstalling one of them removes only its tab.

Access to a document follows access to the record it belongs to: whoever can
read the record can read its documents, whoever can write the record can edit
them. A record can also lock its documents (`_office_is_locked`), e.g. once it
is Closed.
""",
    'author': 'Jacon',
    'license': 'LGPL-3',
    'depends': ['base', 'mail', 'jacon_core', 'jacon_documents', 'onlyoffice_odoo'],
    'data': [
        'security/jacon_office_groups.xml',
        'security/ir.model.access.csv',
        'data/jacon_office_category_data.xml',
        'data/jacon_office_cron_data.xml',
        'views/jacon_office_category_views.xml',
        'views/jacon_office_document_views.xml',
        'views/res_config_settings_views.xml',
        'wizard/jacon_office_document_create_wizard_views.xml',
        'views/jacon_office_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'jacon_office/static/src/open_editor_action.js',
            'jacon_office/static/src/record_link_type.js',
            'jacon_office/static/src/documents_field/documents_field.js',
            'jacon_office/static/src/documents_field/documents_field.xml',
            'jacon_office/static/src/documents_field/documents_field.scss',
        ],
    },
    'installable': True,
    'application': False,
    'post_init_hook': 'post_init_hook',
}
