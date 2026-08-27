import csv

with open('/tmp/pic_update.csv', encoding='utf-8') as f:
    rows = list(csv.reader(f))
print("total rows:", len(rows))

with env.cr.savepoint():
    for part_number, pic in rows:
        part = env['part_number_manager.part_number'].search([('part_number', '=', part_number)], limit=1)
        if not part:
            print(f"NOT FOUND part {part_number}")
            continue
        if not pic:
            user = env.ref('base.user_admin')
        else:
            user = env['res.users'].search([('name', '=ilike', pic)], limit=1)
            if not user:
                print(f"WOULD CREATE user: {pic}")
                user = None
        old_uid = part.create_uid.name
        new_name = user.name if user else f"[NEW]{pic}"
        print(f"{part_number}: {old_uid} -> {new_name}")
    raise Exception("dry run rollback")
