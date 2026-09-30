"""Rescues images pasted into engineering.change's Background/Description
that never got "adopted" by the record (ir.attachment stuck with res_id=0)
- see the 2608-003/2608-010/2608-013 incident. Odoo's own daily "Base:
Auto-vacuum internal data" cron permanently deletes such orphaned
attachments after a grace period, which is what silently wiped 2608-003's
images. This script finds every currently-orphaned attachment still
referenced by an EC's HTML and re-parents it (res_model/res_id) back onto
that record before the vacuum can claim it. Also reports any <img> src
whose attachment is ALREADY gone (nothing to rescue - the image data itself
is lost, needs re-pasting by the user).

Read-only by default - pass FIX=1 to actually apply the fix.

Usage (PowerShell, from the repo root):
    $env:FIX = "1"   # omit / "0" for a dry-run report only
    Get-Content Scripts\rescue_orphan_ec_images.py | docker compose exec -T -e FIX=$env:FIX odoo odoo shell -d <DB_NAME> --no-http

Or dry-run only:
    Get-Content Scripts\rescue_orphan_ec_images.py | docker compose exec -T odoo odoo shell -d <DB_NAME> --no-http
"""
import os
import re

fix = os.environ.get('FIX') == '1'
IMG_RE = re.compile(r'/web/image/(\d+)-')

ECs = env['engineering.change'].sudo().with_context(active_test=False).search([])
rescued, already_ok, broken = [], [], []

for ec in ECs:
    for field_name in ('description', 'background'):
        html = ec[field_name] or ''
        for att_id in {int(m) for m in IMG_RE.findall(html)}:
            att = env['ir.attachment'].sudo().browse(att_id)
            if not att.exists():
                broken.append((ec.name, ec.id, field_name, att_id))
                continue
            if att.res_model == 'engineering.change' and att.res_id == ec.id:
                already_ok.append((ec.name, ec.id, field_name, att_id))
                continue
            rescued.append((ec.name, ec.id, field_name, att_id, att.res_model, att.res_id))
            if fix:
                att.write({'res_model': 'engineering.change', 'res_id': ec.id})

print('=== Already fine: %d ===' % len(already_ok))
print('=== %s orphaned (res_id/res_model mismatch): %d ===' % ('RESCUED' if fix else 'WOULD RESCUE', len(rescued)))
for name, ec_id, field_name, att_id, old_model, old_res_id in rescued:
    print('  EC %s (id %s) %s -> attachment %s (was res_model=%s res_id=%s)'
          % (name, ec_id, field_name, att_id, old_model, old_res_id))
print('=== BROKEN - attachment already deleted, image lost, needs re-paste: %d ===' % len(broken))
for name, ec_id, field_name, att_id in broken:
    print('  EC %s (id %s) %s -> attachment %s MISSING' % (name, ec_id, field_name, att_id))

if fix and rescued:
    env.cr.commit()
    print('Committed %d fix(es).' % len(rescued))
elif rescued:
    print('Dry-run only - nothing written. Re-run with FIX=1 to apply.')
