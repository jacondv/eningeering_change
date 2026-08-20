from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Equipment Models used to belong directly to a Category (`category_id`);
    a Product Family level was inserted between them. For every Category that
    already had Models, create one "General" Family under it and re-home
    those Models there, so no existing Category assignment is lost - the
    `category_id` column itself is dropped afterwards by the ORM schema
    update since the field no longer exists on the model.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    cr.execute("SELECT DISTINCT category_id FROM equipment_model WHERE category_id IS NOT NULL")
    category_ids = [row[0] for row in cr.fetchall()]
    for category_id in category_ids:
        family = env['equipment.model.family'].create({
            'name': 'General',
            'category_id': category_id,
        })
        cr.execute(
            "UPDATE equipment_model SET family_id = %s WHERE category_id = %s",
            (family.id, category_id),
        )
