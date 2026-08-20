{
    'name': 'Jacon Customer Site',
    'version': '19.0.1.0.0',
    'category': 'Sales/CRM',
    'summary': 'Delivery Sites, many-to-many with Customers',
    'description': """
Jacon Customer Site
====================
Manages delivery "Site" contacts (where equipment is shipped/installed) and
their relationship to Customers. A Site is a `res.partner` (address type
"Site") and can be linked to any number of Customers, and a Customer can
have any number of Sites - a Site does not have to belong to any Customer
at all, it can stand on its own and be linked in later.

- Adds a "Site" address type to Contacts, with its own menu under Contacts.
- Many2many relationship between Customers and Sites (Sites tab on the
  Customer form, Customers tab on the Site form).
- Project form/list "Site" field: quick-create a new Site or Customer right
  from the field, and picking a Customer auto-suggests its existing Sites.
""",
    'author': 'Jacon',
    'license': 'LGPL-3',
    'depends': ['base', 'contacts', 'project'],
    'data': [
        'views/res_partner_views.xml',
        'views/project_project_views.xml',
    ],
    'installable': True,
    'application': False,
}
