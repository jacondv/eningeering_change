"""Splits the old combined `description` (which carried a marked-off
'ec-background-block' box, extracted at report-render time by the now-removed
_split_description_background) into the two new plain fields: `background`
and `description`. Runs once, before the module's own `description` column
loses that box's content to the field's plain new default. Records without
the box are left with background empty and their full description unchanged.
"""
from lxml import html as lxml_html


def _split_description_background(description):
    if not description:
        return '', ''
    try:
        root = lxml_html.fragment_fromstring(description, create_parent='div')
    except Exception:
        return '', description

    def _inner_html(node):
        return (node.text or '') + ''.join(
            lxml_html.tostring(child, encoding='unicode') for child in node)

    matches = root.find_class('ec-background-block')
    matched_ids = {id(el) for el in matches}
    blocks = [
        el for el in matches
        if not any(id(anc) in matched_ids for anc in el.iterancestors())
    ]

    parts = []
    for block in blocks:
        for node in block.iter():
            node.attrib.pop('style', None)
            node.attrib.pop('class', None)
        first = next(iter(block), None)
        if first is not None and (first.text or '').strip().rstrip(':').lower() == 'background':
            tail = first.tail or ''
            block.remove(first)
            block.text = (block.text or '') + tail
        content = _inner_html(block).strip()
        if content:
            if block.tag in ('ul', 'ol'):
                parts.append(f'<{block.tag}>{content}</{block.tag}>')
            else:
                parts.append(f'<p>{content}</p>')
        block.getparent().remove(block)
    background_html = ''.join(parts)

    def _is_blank_block(el):
        if el.tag not in ('p', 'div'):
            return False
        if (el.text or '').strip().strip('\xa0'):
            return False
        return all(child.tag == 'br' and not (child.tail or '').strip() for child in el)

    def _is_content_label(el):
        return 'ec-content-label' in (el.get('class') or '').split()

    while len(root) and not (root.text or '').strip() and (
            _is_blank_block(root[0]) or _is_content_label(root[0])):
        root.remove(root[0])

    return background_html, _inner_html(root)


def migrate(cr, version):
    # Raw SQL, not the ORM: write() on this model enforces a field-edit
    # guard (only the Request role in Draft, or the approver currently
    # holding the request, may touch `description`) that would wrongly
    # block this one-time backfill for any request no longer in an open
    # stage - Closed/Rejected requests included, which have every right to
    # keep their historical Background content split out correctly.
    cr.execute("SELECT id, description FROM engineering_change WHERE description LIKE %s",
               ('%ec-background-block%',))
    for change_id, description in cr.fetchall():
        background_html, rest_html = _split_description_background(description)
        cr.execute(
            "UPDATE engineering_change SET background = %s, description = %s WHERE id = %s",
            (background_html, rest_html, change_id))
