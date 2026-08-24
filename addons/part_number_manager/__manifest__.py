{
    'name': 'Part Number Manager',
    'version': '19.0.1.0.0',
    'category': 'Manufacturing',
    'summary': 'Generate and manage company part numbers, independent from product.product',
    'description': """
Part Number Manager
====================
Manages company part numbers as a standalone model, separate from
`product.product` / `product.template`.

Features:
- Auto-generated, gap-filling part numbers (Material Group code + sequence suffix), never entered by hand
- N-N mapping between legacy and new codes across code-format conversions
- Dynamic (EAV) attributes for BOM-built parts, per Part Type
- Dedicated OWL entry page combining "Create New" and "Convert Legacy Code" flows, with server-side preview and per-row partial-success/retry save
""",
    'author': 'Jacon',
    'license': 'LGPL-3',
    'depends': ['base', 'mail', 'project', 'base_import', 'jacon_core'],
    'data': [
        'security/part_number_manager_groups.xml',
        'security/ir.model.access.csv',
        'data/part_number_import_mapping_data.xml',
        'views/material_category_views.xml',
        'views/material_group_views.xml',
        'views/part_type_views.xml',
        'views/part_attribute_views.xml',
        'views/part_number_views.xml',
        'views/part_management_page_actions.xml',
        'views/part_number_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'part_number_manager/static/src/part_management_page/part_management_page.scss',
            'part_number_manager/static/src/part_management_page/part_management_page.js',
            'part_number_manager/static/src/part_management_page/part_management_page.xml',
            'part_number_manager/static/src/part_number_lock/part_number_unlock_dialog.js',
            'part_number_manager/static/src/part_number_lock/part_number_unlock_dialog.xml',
            'part_number_manager/static/src/part_number_lock/part_number_edit_lock_field.js',
            'part_number_manager/static/src/part_number_lock/part_number_edit_lock_field.xml',
            'part_number_manager/static/src/part_number_lock/part_number_field_readonly_patch.js',
            'part_number_manager/static/src/part_number_lock/part_number_relock_on_save_patch.js',
            'part_number_manager/static/src/part_number_lock/part_number_state_confirm_patch.js',
        ],
    },
    'installable': True,
    'application': True,
}
