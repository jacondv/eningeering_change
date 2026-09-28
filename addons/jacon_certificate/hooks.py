def pre_init_hook(env):
    """`equipment.certificate` used to live in `equipment_model`. Re-point the
    ir.model/ir.model.fields xmlids to this module *before* this module's own
    models are reflected, so the existing table/columns (and the certificate
    tree data users already entered) are reused in place instead of the old
    module's end-of-upgrade orphan cleanup dropping them.
    """
    env.cr.execute("""
        UPDATE ir_model_data
        SET module = 'jacon_certificate'
        WHERE module = 'equipment_model'
          AND ((model = 'ir.model' AND name = 'model_equipment_certificate')
            OR (model = 'ir.model.fields' AND name LIKE 'field_equipment_certificate_%'))
    """)
