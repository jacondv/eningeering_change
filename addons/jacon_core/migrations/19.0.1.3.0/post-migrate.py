"""Moves every existing row from the old, Task-only project.task.description.log
into the new, generic jacon.field.change.log (res_model/res_id/field_name) -
the model that used to own that table has been removed in favor of the
jacon.field.change.log.mixin pattern (see project_task.py), which any model
can now use. Nothing in the History smart button's behavior changes for the
end user - same rows, same content, just in the new shared table.
"""


def migrate(cr, version):
    cr.execute("""
        INSERT INTO jacon_field_change_log
            (res_model, res_id, field_name, user_id, date, diff,
             create_uid, create_date, write_uid, write_date)
        SELECT 'project.task', task_id, 'description', user_id, date, diff,
               create_uid, create_date, write_uid, write_date
        FROM project_task_description_log
    """)
    cr.execute("DROP TABLE IF EXISTS project_task_description_log")
