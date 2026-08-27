#!/bin/bash
# Update Part Number "Created By" from an Excel PIC column.
# Usage: ./update_pic.sh <db_name> <path_to_xlsx_on_host> [part_number_col_index] [pic_col_index]
#   indices are 0-based, default 3 (PartNumber) and 13 (PIC) matching the
#   original test.xlsx layout - pass different numbers if a prod file's
#   columns are in different positions.
#
# Backs up the DB, copies the file into the odoo container, converts it to
# CSV, prints a dry-run (no DB changes) for review, asks for confirmation,
# then applies the update for real.

set -e

DB="$1"
XLSX_PATH="$2"
PN_COL="${3:-3}"
PIC_COL="${4:-13}"

if [ -z "$DB" ] || [ -z "$XLSX_PATH" ]; then
    echo "Usage: $0 <db_name> <path_to_xlsx> [part_number_col_index] [pic_col_index]"
    exit 1
fi

if [ ! -f "$XLSX_PATH" ]; then
    echo "File not found: $XLSX_PATH"
    exit 1
fi

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="backup_before_pic_update_${DB}_${TIMESTAMP}.sql"

echo "=== 1/5: Backing up $DB to $BACKUP_FILE ==="
docker compose exec -T db pg_dump -U odoo "$DB" > "$BACKUP_FILE"
echo "Backup saved: $BACKUP_FILE"

echo "=== 2/5: Copying $XLSX_PATH into container ==="
docker compose cp "$XLSX_PATH" odoo:/tmp/pic_update_source.xlsx

echo "=== 3/5: Converting Excel to CSV ==="
docker compose exec -T odoo python3 -c "
import openpyxl, csv
wb = openpyxl.load_workbook('/tmp/pic_update_source.xlsx', data_only=True)
ws = wb.worksheets[0]
rows = list(ws.iter_rows(min_row=2, values_only=True))
with open('/tmp/pic_update.csv', 'w', newline='', encoding='utf-8') as f:
    w = csv.writer(f)
    for r in rows:
        pn = str(r[$PN_COL]).strip() if r[$PN_COL] is not None else ''
        pic = (r[$PIC_COL] or '').strip() if r[$PIC_COL] is not None else ''
        if pn:
            w.writerow([pn, pic])
print(f'{len(rows)} rows converted')
"

echo "=== 4/5: Dry run (no changes committed) - review carefully ==="
docker compose exec -T odoo odoo shell -d "$DB" --no-http <<'PYEOF'
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
PYEOF

echo ""
read -p "Dry run above looks correct? Apply for real on '$DB'? [y/N] " CONFIRM
if [ "$CONFIRM" != "y" ] && [ "$CONFIRM" != "Y" ]; then
    echo "Aborted - no changes made."
    exit 0
fi

echo "=== 5/5: Applying update for real ==="
docker compose exec -T odoo odoo shell -d "$DB" --no-http <<'PYEOF'
import csv, re
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
PYEOF

echo "=== Done. Backup kept at $BACKUP_FILE in case you need to restore. ==="
