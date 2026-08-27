import csv
import re

with open('/tmp/pic_update.csv', encoding='utf-8') as f:
    rows = list(csv.reader(f))


def slugify_login(name):
    base = re.sub(r'[^a-zA-Z]+', '.', name).strip('.').lower()
    login = base
    i = 1
    while env['res.users'].search([('login', '=', login)], limit=1):
        i += 1
        login = f'{base}{i}'
    return login


updated = 0
created_users = []
for part_number, pic in rows:
    part = env['part_number_manager.part_number'].search([('part_number', '=', part_number)], limit=1)
    if not part:
        print(f"SKIP - part not found: {part_number}")
        continue
    if not pic:
        user = env.ref('base.user_admin')
    else:
        user = env['res.users'].search([('name', '=ilike', pic)], limit=1)
        if not user:
            user = env['res.users'].create({'name': pic, 'login': slugify_login(pic)})
            created_users.append(pic)
    env.cr.execute(
        "UPDATE part_number_manager_part_number SET create_uid = %s WHERE id = %s",
        (user.id, part.id),
    )
    updated += 1

env.cr.commit()
print(f"Updated {updated} parts. Created users: {created_users}")
