{
    'name': 'Part Documents',
    'version': '19.0.1.0.0',
    'category': 'Productivity',
    'summary': 'Datasheets, manuals, drawings and notes for part numbers: files, links, shared-folder paths and free text',
    'description': """
Part Documents
==============
Keeps the documents of part numbers (datasheets, manuals, drawings, certificates, notes) in one place and
makes them searchable by part number, vendor, title...

A document is either a File (PDF or image, stored here), a Link, a Path in the shared OneDrive/SharePoint
folder (kept relative, so it opens on every PC that syncs the folder) or free text. One document can belong
to many part numbers; adding the same file, link or path twice is noticed.

Access is granted per person: Settings > Users > Access Rights > Part Documents (View, Edit, Manage).
""",
    'author': 'Jacon',
    'license': 'LGPL-3',
    'depends': ['base', 'mail', 'part_number_manager', 'jacon_documents'],
    'data': [
        'security/pnd_groups.xml',
        'security/ir.model.access.csv',
        'data/pnd_data.xml',
        'views/pnd_document_views.xml',
        'views/pnd_document_type_views.xml',
        'views/pnd_config_views.xml',
        'views/part_number_views.xml',
        'wizard/pnd_document_merge_wizard_views.xml',
        'views/pnd_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'part_number_docs/static/src/open_path/pnd_open_path.js',
            'part_number_docs/static/src/search_page/pnd_layout.js',
            'part_number_docs/static/src/search_page/pnd_search_page.js',
            'part_number_docs/static/src/search_page/pnd_search_page.xml',
            'part_number_docs/static/src/search_page/pnd_search_page.scss',
        ],
    },
    'post_init_hook': 'grant_view_to_current_users',
    'installable': True,
    'application': False,
}
