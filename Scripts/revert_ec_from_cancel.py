"""Reverts one engineering.change record that was accidentally Canceled back
to whatever state it was in right before the Cancel - read from its own
Chatter tracking history, not hardcoded to Draft. Run via `odoo shell`
piped into stdin (see the docker compose exec one-liner in
Scripts/revert_ec_from_cancel.cmd.txt); reads the record's name from the
EC_NAME environment variable so this file itself never needs editing.

usage:
    Get-Content Scripts\revert_ec_from_cancel.py | docker compose exec -T -e EC_NAME=2609-023 odoo odoo shell -d jacon_plm --no-http

"""
import os

EC_NAME = os.environ['EC_NAME']

rec = env['engineering.change'].search([('name', '=', EC_NAME)], limit=1)
if not rec:
    raise Exception(f"Khong tim thay EC '{EC_NAME}'")
if rec.state != 'canceled':
    raise Exception(f"EC '{EC_NAME}' dang o state '{rec.state}', khong phai 'canceled' - khong chay tiep.")

key_to_label = dict(rec._fields['state'].selection)
label_to_key = {v: k for k, v in key_to_label.items()}
canceled_label = key_to_label['canceled']

field_id = env['ir.model.fields']._get('engineering.change', 'state').id
history = env['mail.tracking.value'].sudo().search([
    ('mail_message_id.model', '=', 'engineering.change'),
    ('mail_message_id.res_id', '=', rec.id),
    ('field_id', '=', field_id),
], order='id desc')

prev_label = None
for h in history:
    if h.new_value_char == canceled_label:
        prev_label = h.old_value_char
        break
if not prev_label:
    raise Exception("Khong tim thay lich su chuyen sang Canceled trong Chatter.")

target_state = label_to_key.get(prev_label)
if not target_state:
    raise Exception(f"Khong map duoc nhan '{prev_label}' ve state ky thuat.")

print(f"{rec.name}: canceled -> {target_state} ({prev_label})")
rec.with_context(ec_workflow_write=True).write({'state': target_state, 'reject_reason': False})
rec.message_post(body=f"State manually reverted from Rejected (accidental Cancel) back to {prev_label}.")
env.cr.commit()
print("done ->", rec.state)
