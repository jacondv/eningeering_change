"""Fill `{{placeholders}}` of an Office file with values (the document's Rev, state, author...).

The stored file keeps its placeholders: they are filled only in the copy that is shown, converted
to PDF or downloaded, so a new Rev can fill them again with its own values.

Word processors split what is typed into several "runs" whenever the formatting changes or
someone edits in the middle (`{{re` + `v}}`), so a placeholder is looked for in the text of a whole
paragraph and filled in the run where it starts, which keeps that run's formatting.

Only PowerPoint (.pptx) is supported for now; the other kinds come back unchanged.
"""
import io
import re
import zipfile

from lxml import etree

TOKEN_RE = re.compile(r'\{\{\s*([A-Za-z][A-Za-z0-9_.]*)\s*\}\}')

# What the document's own values can be asked for (more come from the record a document belongs to):
# name -> (what it stands for, an example of what it shows).
# Written into the file once, when the document is made; from then on people change them by hand.
CREATION_TOKENS = {
    'author': ("The author", "Nguyen Van A"),
    'category': ("The document's category", "Specification"),
    'description': ("The description", "Main assembly drawings"),
    'belongs_to': ("The name of the record the document belongs to (e.g. the Project)", "Project Alpha"),
    'company': ("The company's name", "Jacon"),
}
# Filled in whenever the file is shown, converted or downloaded: they follow the workflow, so each Rev shows its own.
WORKFLOW_TOKENS = {
    'rev': ("The Rev number", "3"),
    'state': ("Draft, In Review or Released", "Released"),
    'released_by': ("Who released the Rev", "Tran Thi B"),
    'released_date': ("When the Rev was released", "12-Aug-2026"),
    'submitted_by': ("Who submitted the Rev for review", "Nguyen Van A"),
    'last_edit_by': ("Who saved the file last", "Le Van C"),
    'last_edit_date': ("When the file was saved last", "11-Aug-2026"),
}
CATALOG = {name: info[0] for name, info in {**CREATION_TOKENS, **WORKFLOW_TOKENS}.items()}

_A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
# Everything of a presentation that holds text: slides, and also the layouts and masters (where footers
# with the Rev usually are), the notes and the handouts.
_PPTX_PARTS = re.compile(r'^ppt/(slides|slideLayouts|slideMasters|notesSlides|notesMasters|handoutMasters)/[^/]+\.xml$')
_PARTS = {'pptx': _PPTX_PARTS}
_TEXT_RE = re.compile(rb'<a:t(?:\s[^>]*)?>([^<]*)</a:t>')
_PARSER = etree.XMLParser(resolve_entities=False, no_network=True)


def is_supported(kind):
    return kind in _PARTS


def _fill_part(xml, values):
    """Returns (the new xml or None if nothing changed, the names of the placeholders found)."""
    if b'{{' not in b''.join(_TEXT_RE.findall(xml)):
        return None, set()  # cheap way out: most parts have none
    root = etree.fromstring(xml, _PARSER)
    found, changed = set(), False
    for paragraph in root.iter('{%s}p' % _A):
        texts = [t for run in paragraph.findall('{%s}r' % _A) for t in run.findall('{%s}t' % _A)]
        full = ''.join(t.text or '' for t in texts)
        matches = list(TOKEN_RE.finditer(full))
        if not matches:
            continue
        chars = list(full)
        for match in matches:
            name = match.group(1).lower()
            found.add(name)
            if values is not None and name in values:
                chars[match.start()] = str(values[name])
                for index in range(match.start() + 1, match.end()):
                    chars[index] = ''
                changed = True
        if values is not None:
            position = 0
            for text in texts:
                length = len(text.text or '')
                text.text = ''.join(chars[position:position + length])
                position += length
    if not changed:
        return None, found
    return etree.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True), found


def _process(content, kind, values):
    try:
        return _process_zip(content, kind, values)
    except (zipfile.BadZipFile, etree.XMLSyntaxError):
        return None, set()  # a file that can't be read has nothing to fill: it is shown as it is


# What a file may unpack to: a small archive can hold a huge part (a "zip bomb"), and reading it would
# fill the worker's memory.
MAX_PART_SIZE = 100 * 1024 * 1024
MAX_UNPACKED_SIZE = 500 * 1024 * 1024


def unpacked_size_is_ok(archive):
    sizes = [item.file_size for item in archive.infolist()]
    return max(sizes, default=0) <= MAX_PART_SIZE and sum(sizes) <= MAX_UNPACKED_SIZE


def _process_zip(content, kind, values):
    parts = _PARTS.get(kind)
    if not parts:
        return None, set()
    found, filled = set(), {}
    with zipfile.ZipFile(io.BytesIO(content)) as source:
        if not unpacked_size_is_ok(source):
            return None, set()  # not read: shown as it is
        for name in source.namelist():
            if parts.match(name):
                new_xml, names = _fill_part(source.read(name), values)
                found |= names
                if new_xml is not None:
                    filled[name] = new_xml
        if not filled:
            return None, found
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as target:
            for item in source.infolist():
                target.writestr(item, filled[item.filename] if item.filename in filled else source.read(item.filename))
    return output.getvalue(), found


def tokens_in(content, kind):
    """The (lower case) names of the placeholders in the file."""
    return _process(content, kind, None)[1]


def fill(content, kind, values):
    """The file with its placeholders filled from `values` (names in lower case). A placeholder with
    no value is left as it is, so that a mistake in its name shows."""
    return _process(content, kind, values)[0] or content
