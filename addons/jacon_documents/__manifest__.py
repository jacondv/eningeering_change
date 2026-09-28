{
    'name': 'Documents',
    'version': '19.0.1.0.0',
    'category': 'Productivity',
    'summary': 'Umbrella app grouping Jacon\'s document-authoring/reporting addons under one menu',
    'description': """
Documents
=========
Holds no business logic of its own - just the single root "Documents" App
menu that other Jacon addons (QC Check Sheet, Certificate, and future
document types) attach their own menu under, via `parent`.

Adding a new document-type addon later only requires it to depend on this
module and point its own root menu's `parent` at `menu_jacon_documents_root`
- nothing here needs to change.
""",
    'author': 'Jacon',
    'license': 'LGPL-3',
    'depends': ['base'],
    'data': [
        'views/jacon_documents_menus.xml',
    ],
    'installable': True,
    'application': True,
}
