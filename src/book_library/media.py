"""On-demand viewing of referenced local raster illustrations.

The index grants access only to image members actually discovered by the
extractor. Source archives remain in place, and no member is extracted to disk.
"""
from __future__ import annotations

import gzip
import json
import os
from pathlib import Path
import re
import stat
import zipfile

MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_DESCRIPTION_CHARS = 4000


class MediaUnavailable(ValueError):
    """An illustration cannot be safely served from its current source."""


def _member_name(member: str) -> str:
    if not isinstance(member, str) or not member or len(member) > 2048:
        raise MediaUnavailable('Choose a valid source illustration.')
    parts = member.split('/')
    if member.startswith('/') or re.match(r'^[A-Za-z]:', member) or '\\' in member or '\x00' in member or any(part in ('', '.', '..') for part in parts):
        raise MediaUnavailable('That package image path is not permitted.')
    return member


def _current_source(library, file_id: str):
    source = library._catalog()['files'].get(file_id)
    if not source or not source.get('available') or source.get('state') != 'ready':
        raise MediaUnavailable('That source is unavailable. Synchronize the library before opening its illustration.')
    path = Path(source['path'])
    try:
        if path.is_symlink() or path.suffix.lower() not in ('.docx', '.epub') or library.root.resolve() not in path.resolve().parents:
            raise MediaUnavailable('The illustration source is outside this library.')
        current = path.stat()
    except OSError:
        raise MediaUnavailable('The illustration source is no longer available. Synchronize the library.') from None
    if current.st_size != source.get('size') or current.st_mtime_ns != source.get('mtime_ns'):
        raise MediaUnavailable('The illustration source has changed. Synchronize the library before opening it.')
    return source, path


def describe_image(library, file_id: str, member: str) -> dict:
    """Resolve source-provided descriptions without reading original image bytes."""
    member = _member_name(member)
    source, path = _current_source(library, file_id)
    name = source.get('cache', '')
    if not name or Path(name).name != name:
        raise MediaUnavailable('Indexed illustration metadata is unavailable. Synchronize the library.')
    cache = library.state / 'extractions' / name
    try:
        if cache.is_symlink() or cache.parent.resolve() != (library.state / 'extractions').resolve():
            raise MediaUnavailable('Indexed illustration metadata is unavailable.')
        with gzip.open(cache, 'rt', encoding='utf-8') as stream:
            extraction = json.load(stream)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        raise MediaUnavailable('Indexed illustration metadata is unavailable. Synchronize the library.') from None
    matches = [image for image in extraction.get('images', []) if image.get('member') == member]
    if len(matches) != 1:
        raise MediaUnavailable('That image was not referenced in the indexed source.')
    image = matches[0]
    referenced_by = set(image.get('referenced_by', []))
    if not referenced_by:
        raise MediaUnavailable('That image has no verified source reference.')
    blocks = [block for block in extraction.get('blocks', []) if block.get('ordinal') in referenced_by and member in block.get('image_refs', [])]
    if not blocks:
        raise MediaUnavailable('That image has no verified source reference.')
    alt_texts = [str(text).strip()[:MAX_DESCRIPTION_CHARS] for text in image.get('alt_texts', []) if str(text).strip()][:5]
    captions = [block['text'][:MAX_DESCRIPTION_CHARS] for block in blocks if block.get('kind') == 'caption' and block.get('text', '').strip()][:5]
    return {
        'file_id': file_id, 'work_id': source.get('work_id'), 'member': member,
        'filename': path.name, 'source_path': str(path), 'alt_texts': alt_texts,
        'alt': alt_texts[0] if alt_texts else 'Source illustration without a supplied text description.',
        'captions': captions, 'reference_locators': [block.get('locator', {}) for block in blocks[:10]],
        'description_status': 'source_provided' if alt_texts else 'description_missing',
        'declared_media_type': image.get('media_type'),
    }


def _raster_type(data: bytes) -> str:
    # Content sniffing chooses a fixed raster type. A misleading file extension
    # or publisher MIME label can never make HTML/SVG executable in the browser.
    if len(data) >= 24 and data.startswith(b'\x89PNG\r\n\x1a\n') and data[12:16] == b'IHDR':
        return 'image/png'
    if len(data) >= 4 and data.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if len(data) >= 10 and data[:6] in (b'GIF87a', b'GIF89a'):
        return 'image/gif'
    if len(data) >= 16 and data[:4] == b'RIFF' and data[8:12] == b'WEBP' and data[12:16] in (b'VP8 ', b'VP8L', b'VP8X'):
        return 'image/webp'
    raise MediaUnavailable('This illustration is not a supported raster image. Consult the original source for SVG or other formats.')


def load_image(library, file_id: str, member: str) -> tuple[bytes, str, dict]:
    description = describe_image(library, file_id, member)
    source, path = _current_source(library, file_id)
    try:
        # Reject a replaced symlink and verify the opened descriptor, not only
        # the preceding path stat. Opening this image does not rescan other books.
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(descriptor, 'rb') as stream:
            opened = os.fstat(stream.fileno())
            if opened.st_size != source['size'] or opened.st_mtime_ns != source['mtime_ns']:
                raise MediaUnavailable('The source changed while opening this illustration. Synchronize and retry.')
            with zipfile.ZipFile(stream) as package:
                matches = [info for info in package.infolist() if info.filename == member]
                if len(matches) != 1:
                    raise MediaUnavailable('The source image is missing or has ambiguous package entries.')
                info = matches[0]
                if info.is_dir() or stat.S_ISLNK(info.external_attr >> 16) or info.flag_bits & 1:
                    raise MediaUnavailable('That package image entry cannot be opened safely.')
                if info.file_size > MAX_IMAGE_BYTES:
                    raise MediaUnavailable('This illustration exceeds the 20 MiB viewing limit. Consult the original source.')
                with package.open(info) as image:
                    data = image.read(MAX_IMAGE_BYTES + 1)
                if len(data) > MAX_IMAGE_BYTES:
                    raise MediaUnavailable('This illustration exceeds the viewing limit.')
                if len(data) != info.file_size:
                    raise MediaUnavailable('The source illustration is incomplete.')
                media_type = _raster_type(data)
            final = os.fstat(stream.fileno())
            if (opened.st_size, opened.st_mtime_ns) != (final.st_size, final.st_mtime_ns):
                raise MediaUnavailable('The source changed while reading this illustration. Synchronize and retry.')
    except (OSError, zipfile.BadZipFile, RuntimeError, NotImplementedError):
        raise MediaUnavailable('The source illustration could not be read safely. Synchronize the library or consult the original copy.') from None
    return data, media_type, description
