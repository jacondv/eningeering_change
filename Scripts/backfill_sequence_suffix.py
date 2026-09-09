Part = env['part_number_manager.part_number']

recs = Part.search([
    ('material_group_id', '!=', False),
    ('sequence_suffix', '=', False),
    ('is_standard_format', '=', True),
])
print(f"Candidates (standard format, Material Group set, sequence_suffix blank): {len(recs)}")

fixed = 0
skipped = []
for r in recs:
    code = r.material_group_id.code
    if not code or not r.part_number.startswith(code):
        skipped.append(r)
        continue
    suffix = r.part_number[len(code):]
    if not suffix.isdigit():
        skipped.append(r)
        continue
    print(f"{r.part_number}: sequence_suffix '' -> '{suffix}'")
    env.cr.execute(
        "UPDATE part_number_manager_part_number SET sequence_suffix = %s WHERE id = %s",
        (suffix, r.id),
    )
    fixed += 1

if skipped:
    print(f"Skipped (part_number doesn't cleanly match its Material Group's code - needs manual review):")
    for r in skipped:
        print(f"  {r.part_number} (group code: {r.material_group_id.code})")

env.cr.commit()
print(f"Backfilled {fixed} record(s), skipped {len(skipped)}.")
