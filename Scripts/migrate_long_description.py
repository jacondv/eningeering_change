import re
from html import unescape


def strip_html(value):
    text = re.sub(r'<br\s*/?>', '\n', value, flags=re.I)
    text = re.sub(r'</p>|</div>', '\n', text, flags=re.I)
    text = re.sub(r'<[^>]+>', '', text)
    text = unescape(text)
    lines = [line.strip() for line in text.splitlines()]
    return '\n'.join(line for line in lines if line).strip()


parts = env['part_number_manager.part_number'].search([('long_description', '!=', False)])
tag_re = re.compile(r'<[^>]+>')
has_html = [p for p in parts if tag_re.search(p.long_description or '')]

print(f"total with long_description: {len(parts)}")
print(f"with HTML tags to strip: {len(has_html)}")

for p in has_html:
    new_value = strip_html(p.long_description)
    print(f"{p.part_number}: {p.long_description[:60]!r} -> {new_value!r}")
    env.cr.execute(
        "UPDATE part_number_manager_part_number SET long_description = %s WHERE id = %s",
        (new_value, p.id),
    )

env.cr.commit()
print(f"Stripped {len(has_html)} records.")
