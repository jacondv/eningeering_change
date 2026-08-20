{
    'name': 'Equipment Model',
    'version': '19.0.2.0.0',
    'category': 'Manufacturing',
    'summary': 'Manage the company\'s equipment/machine Model hierarchy',
    'description': """
Equipment Model
================
Product structure: Model Category (product line) > Product Family > Model.
A Model is the abstract product design for one of the company's off-highway
machines (e.g. a specific machine model), which may inherit from a parent
Model. A Project (Job Number) is a concrete customer order - one production
copy of a Model - and is linked here via `project.project.model_id`.

Kept as its own addon so the Model concept is reusable by other modules
(engineering_change, part_number_manager, ...) without pulling in unrelated
business logic.
""",
    'author': 'Jacon',
    'license': 'LGPL-3',
    'depends': ['base', 'project'],
    'data': [
        'security/equipment_model_groups.xml',
        'security/ir.model.access.csv',
        'views/equipment_model_category_views.xml',
        'views/equipment_model_family_views.xml',
        'views/equipment_model_views.xml',
        'views/equipment_model_menus.xml',
    ],
    'installable': True,
    'application': True,
}
