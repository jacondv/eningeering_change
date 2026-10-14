{
    'name': 'Jacon Debranding',
    'version': '19.0.1.0.0',
    'category': 'Hidden/Tools',
    'summary': 'Hide the menus, links and background calls that point to odoo.com',
    'description': """
Jacon Debranding
================
Admin-only switches (Settings > General Settings > Debranding) to hide what
points users at odoo.com on this self-hosted install:

- User menu: "My Odoo.com Account" and "Help"
- Login page: "Powered by Odoo" and "Manage Databases"
- Emails and the customer portal: "Powered by Odoo"
- Browser tab: replace the default "Odoo" title with your own text
- The weekly "Publisher: Update Notification" call that sends database
  statistics to odoo.com

Once switched off, an item is hidden for everyone, administrators included.
""",
    'author': 'Jacon',
    'license': 'LGPL-3',
    'depends': ['base_setup', 'web', 'mail', 'portal'],
    'data': [
        'views/res_config_settings_views.xml',
        'views/templates.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'jacon_debranding/static/src/debranding.js',
        ],
    },
    'post_init_hook': 'post_init_hook',
    'uninstall_hook': 'uninstall_hook',
    'installable': True,
    'application': False,
}
