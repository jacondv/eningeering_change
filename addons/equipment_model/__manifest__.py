{
    'name': 'Equipment Model',
    'version': '19.0.2.1.0',
    'category': 'Manufacturing',
    'summary': 'Manage the company\'s equipment/machine Model hierarchy',
    'description': """
Equipment Model
================
Product structure: Model Category (product line, "Group") > Product Family > Model.
A Model is the abstract product design for one of the company's off-highway
machines (e.g. a specific machine model), which may inherit from a parent
Model. A Project (Job Number) is a concrete customer order - one production
copy of a Model - and is linked here via `project.project.model_id`.

Kept as its own addon so the Model concept is reusable by other modules
(engineering_change, part_number_manager, ...) without pulling in unrelated
business logic.

- Dashboard: how many Groups, Product Families, Models and Jobs, per Group and
  per Product Family, and what still needs sorting out (Models without a
  Product Family, Jobs without a Model). Every figure opens its list.
- Import / Export: one Excel layout both ways (Group, Product Family, Model,
  Parent Model, Job). Import matches names, so re-importing an edited export
  updates instead of duplicating, and it shows a preview before saving anything.
- Names are unique at every level, ignoring case.
- Job names: a Suggest button on the Project form proposes
  <Product Family>-<next number of its Group>. Each Group keeps its Last Job
  Number, moved up whenever a Job named that way is saved.
""",
    'author': 'Jacon',
    'license': 'LGPL-3',
    'depends': ['base', 'project', 'web_hierarchy'],
    'data': [
        'security/equipment_model_groups.xml',
        'security/ir.model.access.csv',
        'views/equipment_model_category_views.xml',
        'views/equipment_model_family_views.xml',
        'views/equipment_model_views.xml',
        'views/equipment_model_dashboard_views.xml',
        'views/project_project_views.xml',
        'wizard/equipment_model_import_wizard_views.xml',
        'views/equipment_model_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'equipment_model/static/src/**/*',
        ],
    },
    'installable': True,
    'application': True,
}
