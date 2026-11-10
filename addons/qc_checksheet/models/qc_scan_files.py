"""The files of a signed scan: what is accepted, and how to make a big one smaller.

Plain functions, no database: the Job sheet's upload and its size estimate both use them,
so what the estimate promises is what the upload then stores.

PyMuPDF's own rewrite_images() was tried first and left out: it only lowers the resolution
of a picture by whole factors (halving it), so a 200 dpi scan, or a 150 dpi one, stays as it
is and a scan comes out only a few percent smaller. Here every picture of a PDF is brought
to the exact resolution of the level, and optionally to grey, with Pillow.
"""
import io
import logging
import os

from odoo import _
from odoo.exceptions import UserError

try:
    import pymupdf
except ImportError:  # older PyMuPDF
    try:
        import fitz as pymupdf
    except ImportError:
        pymupdf = None

_logger = logging.getLogger(__name__)

# The limits are Settings (QC Check Sheet > Configuration > Settings); these are what they start as.
SCAN_MAX_FILE_MB_PARAM = 'qc_checksheet.scan_max_file_mb'
DEFAULT_MAX_FILE_MB = 25
MAX_FILE_SIZE = DEFAULT_MAX_FILE_MB * 1024 * 1024
MAX_FILES = 10
# How far a scan can be reduced. A picture is only touched when it is sharper than the level asks:
#   dpi     resolution its pictures are brought down to (an A4 page is 8.27 inches wide)
#   quality JPEG quality, out of 100
#   gray    whether colour goes, which a signed black-on-white form doesn't need
#   side    the longest side, in pixels, of a JPG or PNG photo of a sheet
LEVELS = {
    'standard': {'dpi': 200, 'quality': 70, 'gray': False, 'side': 2338},
    'strong': {'dpi': 110, 'quality': 50, 'gray': True, 'side': 1280},
}
# Below this share above the target, a picture is not worth resampling: only re-encoded.
DPI_TOLERANCE = 1.08
KINDS = {
    'pdf': ('application/pdf', {'.pdf'}),
    'jpeg': ('image/jpeg', {'.jpg', '.jpeg'}),
    'png': ('image/png', {'.png'}),
}


def max_file_size(env):
    """The largest file a scan may hold, in bytes: the Setting, 25 MB unless changed."""
    value = env['ir.config_parameter'].sudo().get_param(SCAN_MAX_FILE_MB_PARAM)
    # Nothing set is False, which int() would read as 0: the default applies, not the smallest limit.
    try:
        megabytes = int(value) if value else DEFAULT_MAX_FILE_MB
    except ValueError:
        megabytes = DEFAULT_MAX_FILE_MB
    return max(megabytes, 1) * 1024 * 1024


def detect_kind(data):
    """'pdf', 'jpeg' or 'png' by what the bytes are, whatever the file is called."""
    if data[:5] == b'%PDF-':
        return 'pdf'
    if data[:3] == b'\xff\xd8\xff':
        return 'jpeg'
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return 'png'
    return None


def check_file(name, data, max_size=MAX_FILE_SIZE):
    """The kind of a file that may be uploaded; raises a UserError saying why not."""
    if not data:
        raise UserError(_("%s is empty.", name))
    if len(data) > max_size:
        raise UserError(_(
            "%(name)s is %(size)s, over the %(limit)s a file may be. Reduce its size first.",
            name=name, size=human_size(len(data)), limit=human_size(max_size)))
    kind = detect_kind(data)
    extension = os.path.splitext(name)[1].lower()
    if not kind or extension not in KINDS[kind][1]:
        raise UserError(_("%s is not a PDF, JPG or PNG file.", name))
    return kind


def human_size(size):
    """1536 -> '1.5 KB'."""
    value = float(size)
    for unit in ('B', 'KB', 'MB'):
        if value < 1024 or unit == 'MB':
            return f'{value:.0f} {unit}' if unit == 'B' else f'{value:.1f} {unit}'
        value /= 1024


def _flatten(image):
    """An RGB or grey picture from whatever mode: transparency goes onto white, CMYK and palettes to RGB."""
    from PIL import Image

    if image.mode in ('RGBA', 'LA') or (image.mode == 'P' and 'transparency' in image.info):
        image = image.convert('RGBA')
        flat = Image.new('RGB', image.size, (255, 255, 255))
        flat.paste(image, mask=image.split()[-1])
        return flat
    if image.mode not in ('RGB', 'L'):
        return image.convert('RGB')
    return image


def _encode(image, level, gray):
    out = io.BytesIO()
    if gray:
        image = image.convert('L')
    image.save(out, 'JPEG', quality=LEVELS[level]['quality'], optimize=True)
    return out.getvalue()


def _compress_image(name, data, kind, level):
    from PIL import Image, ImageOps

    settings = LEVELS[level]
    image = _flatten(ImageOps.exif_transpose(Image.open(io.BytesIO(data))))
    image.thumbnail((settings['side'], settings['side']), Image.LANCZOS)
    new_name = name if kind == 'jpeg' else os.path.splitext(name)[0] + '.jpg'
    return new_name, _encode(image, level, settings['gray'])


def _compress_pdf(data, level):
    """The PDF with each of its pictures at the level's resolution, quality and colour, or None without PyMuPDF."""
    if pymupdf is None:
        return None
    from PIL import Image

    settings = LEVELS[level]
    try:
        document = pymupdf.open(stream=data, filetype='pdf')
    except Exception:
        raise UserError(_("This PDF can't be read."))
    try:
        if document.needs_pass:
            raise UserError(_("This PDF is password protected and can't be reduced."))
        done = set()
        for page in document:
            for item in page.get_images(full=True):
                xref, smask = item[0], item[1]
                # get_images: (xref, smask, width, height, bits per component, ...). A picture with transparency,
                # or one already in black and white (1 bit), is better left as it is.
                if xref in done or smask or item[4] == 1:
                    continue
                done.add(xref)
                try:
                    info = document.extract_image(xref)
                    if info.get('ext') not in ('jpeg', 'jpg', 'png') or info.get('bpc') == 1:
                        continue
                    picture = _flatten(Image.open(io.BytesIO(info['image'])))
                    rects = page.get_image_rects(xref)
                    dpi = max(picture.width / (rect.width / 72) for rect in rects if rect.width) if rects else None
                    if dpi and dpi > settings['dpi'] * DPI_TOLERANCE:
                        scale = settings['dpi'] / dpi
                        picture = picture.resize(
                            (max(1, round(picture.width * scale)), max(1, round(picture.height * scale))), Image.LANCZOS)
                    encoded = _encode(picture, level, settings['gray'])
                    if len(encoded) < len(info['image']):
                        page.replace_image(xref, stream=encoded)
                except Exception:
                    # One picture that can't be handled stays as it is; the rest is still reduced.
                    _logger.warning("Scan reduction: picture %s left as it is", xref, exc_info=True)
        return document.tobytes(garbage=4, deflate=True, clean=True)
    finally:
        # The document holds native memory: freed here, not whenever the garbage collector comes.
        document.close()


def compress(name, data, level='standard', max_size=MAX_FILE_SIZE):
    """The file made smaller if that can be done: {name, data, mimetype, original_size, size, reduced}.

    A file that doesn't get smaller is returned as it came, so reducing never makes one bigger.
    """
    kind = check_file(name, data, max_size)
    new_name, new_data = name, data
    try:
        if kind == 'pdf':
            result = _compress_pdf(data, level)
            if result is not None:
                new_data = result
        else:
            new_name, new_data = _compress_image(name, data, kind, level)
    except UserError:
        raise
    except Exception:
        _logger.warning("Scan reduction of %s failed; stored as it is", name, exc_info=True)
        new_name, new_data = name, data
    if len(new_data) >= len(data):
        new_name, new_data = name, data
    final_kind = detect_kind(new_data)
    return {
        'name': new_name,
        'data': new_data,
        'mimetype': KINDS[final_kind][0],
        'original_size': len(data),
        'size': len(new_data),
        'reduced': len(new_data) < len(data),
    }
