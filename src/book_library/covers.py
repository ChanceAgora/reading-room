"""Small, local cover thumbnails with source-supported selection.

Cover discovery is independent of extraction and semantic indexing. Only explicit
EPUB declarations or unambiguous cover-marked source elements authorize an image;
the ordinary illustration endpoint retains its stricter indexed-reference rule.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import stat
import tempfile
import threading
import warnings
import xml.etree.ElementTree as ET
import zipfile
import zlib

from PIL import Image, ImageOps, UnidentifiedImageError

from .extract import CONTAINER, EPUB, OPF, XML_ID, ExtractionError, _resolve
from .media import MAX_IMAGE_BYTES, MediaUnavailable, _current_source, _member_name, _raster_type

CACHE_VERSION = 1
MAX_XML_BYTES = 4 * 1024 * 1024
MAX_CACHE_BYTES = 256 * 1024
MAX_PIXELS = 20_000_000
THUMBNAIL_SIZE = (192, 288)
_DECODERS = threading.BoundedSemaphore(2)
_LOADERS = threading.BoundedSemaphore(3)
_COVER_IDS = {'cover', 'cover_page', 'cover-page', 'frontcover', 'front_cover', 'front-cover'}


def _local(tag: str) -> str:
    return tag.rsplit('}', 1)[-1]


def _target(base: str, href: str) -> dict:
    if not href:
        raise MediaUnavailable('The cover reference is incomplete.')
    try:
        target = _resolve(base, href)
    except (ExtractionError, ValueError, UnicodeError):
        raise MediaUnavailable('The cover reference is not a safe local package path.') from None
    if target is None:
        raise MediaUnavailable('Remote cover references are not fetched.')
    _member_name(target['member'])
    return target


class _CoverPackage:
    def __init__(self, stream):
        self.archive = zipfile.ZipFile(stream)
        infos = self.archive.infolist()
        if len(infos) > 100000 or len({i.filename for i in infos}) != len(infos):
            self.archive.close()
            raise MediaUnavailable('The cover package has too many or duplicate entries.')
        if sum(i.file_size for i in infos) > 4 * 1024**3:
            self.archive.close()
            raise MediaUnavailable('The cover package exceeds the expanded-size limit.')
        self.infos = {i.filename: i for i in infos}
        self.xml_reads = 0

    def read(self, member: str, maximum: int) -> bytes:
        _member_name(member)
        info = self.infos.get(member)
        if info is None or info.is_dir() or stat.S_ISLNK(info.external_attr >> 16) or info.flag_bits & 1:
            raise MediaUnavailable('That cover package entry cannot be opened safely.')
        if info.file_size > maximum:
            raise MediaUnavailable('The cover package entry exceeds its reading limit.')
        with self.archive.open(info) as stream:
            data = stream.read(maximum + 1)
        if len(data) != info.file_size or len(data) > maximum:
            raise MediaUnavailable('The cover package entry is incomplete or oversized.')
        return data

    def xml(self, member: str) -> ET.Element:
        self.xml_reads += 1
        if self.xml_reads > 24:
            raise MediaUnavailable('The cover declarations exceed the discovery limit.')
        data = self.read(member, MAX_XML_BYTES)
        if b'<!ENTITY' in data.replace(b'\x00', b'').upper():
            raise MediaUnavailable('Cover XML entity declarations are unsupported.')
        return ET.fromstring(data)


@contextmanager
def _package(source: dict, path: Path):
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(descriptor, 'rb') as stream:
        opened = os.fstat(stream.fileno())
        expected = (source['size'], source['mtime_ns'])
        if (opened.st_size, opened.st_mtime_ns) != expected:
            raise MediaUnavailable('The cover source changed. Synchronize and retry.')
        package = _CoverPackage(stream)
        try:
            yield package
            final = os.fstat(stream.fileno())
            if (final.st_size, final.st_mtime_ns) != expected:
                raise MediaUnavailable('The cover source changed while reading it.')
        finally:
            package.archive.close()


def _page_images(package: _CoverPackage, target: dict) -> set[str]:
    """Resolve an explicitly designated cover page, optionally scoped by ID."""
    member = target['member']
    document = package.xml(member)
    nodes = [document]
    if target.get('element_id'):
        nodes = [node for node in document.iter() if (node.get('id') or node.get(XML_ID)) == target['element_id']]
        if len(nodes) != 1:
            raise MediaUnavailable('The cover-page reference is ambiguous or missing.')
    images = set()
    for node in nodes[0].iter():
        if _local(node.tag) == 'img' and node.get('src'):
            images.add(_target(member, node.get('src'))['member'])
    if len(images) != 1:
        raise MediaUnavailable('The designated cover page does not identify one raster cover.')
    return images


def _cover_members(package: _CoverPackage, target: dict, opf: str, items: dict) -> set[str]:
    for item in items.values():
        try:
            item_target = _target(opf, item.get('href', ''))
        except MediaUnavailable:
            continue  # Unrelated external resources are never fetched.
        if item_target['member'] == target['member'] and item.get('media-type', '').startswith('image/'):
            return {target['member']}
    return _page_images(package, target)


def _discover(package: _CoverPackage) -> tuple[str, list[str]] | None:
    container = package.xml('META-INF/container.xml')
    if container.tag != CONTAINER + 'container':
        raise MediaUnavailable('The EPUB container is invalid.')
    roots = container.findall(CONTAINER + 'rootfiles/' + CONTAINER + 'rootfile')
    if not roots or len(roots) > 4:
        raise MediaUnavailable('The EPUB package declaration is missing or ambiguous.')
    candidates: dict[str, set[str]] = {}
    marker_pages: list[str] = []

    def add(member: str, reason: str):
        candidates.setdefault(member, set()).add(reason)

    for root in roots:
        opf = _target('', root.get('full-path', ''))['member']
        document = package.xml(opf)
        if document.tag != OPF + 'package':
            raise MediaUnavailable('The EPUB package is invalid.')
        items = {}
        for item in document.findall(OPF + 'manifest/' + OPF + 'item'):
            key = item.get('id')
            if not key or key in items:
                raise MediaUnavailable('The EPUB manifest has ambiguous identities.')
            items[key] = item
            if 'cover-image' in item.get('properties', '').split():
                add(_target(opf, item.get('href', ''))['member'], 'EPUB cover-image declaration')
        for meta in document.findall(OPF + 'metadata/' + OPF + 'meta'):
            if meta.get('name', '').casefold() == 'cover':
                item = items.get(meta.get('content'))
                if item is None:
                    raise MediaUnavailable('The declared cover is absent from the manifest.')
                add(_target(opf, item.get('href', ''))['member'], 'EPUB legacy cover declaration')
        for ref in document.findall(OPF + 'guide/' + OPF + 'reference'):
            if ref.get('type', '').casefold() in {'cover', 'coverpage'}:
                target = _target(opf, ref.get('href', ''))
                for member in _cover_members(package, target, opf, items):
                    add(member, 'EPUB cover guide')
        for item in items.values():
            if 'nav' in item.get('properties', '').split():
                target = _target(opf, item.get('href', ''))
                nav = package.xml(target['member'])
                for link in nav.iter():
                    if _local(link.tag) == 'a' and 'cover' in link.get(EPUB + 'type', '').split():
                        for member in _cover_members(package, _target(target['member'], link.get('href', '')), opf, items):
                            add(member, 'EPUB cover landmark')
        # Bookshare-style source cover markers sometimes have no OPF cover tag.
        # Inspect only the opening spine documents, never choose the first image.
        for ref in document.findall(OPF + 'spine/' + OPF + 'itemref')[:6]:
            item = items.get(ref.get('idref'))
            if item is not None and item.get('media-type') in ('application/xhtml+xml', 'text/html'):
                marker_pages.append(_target(opf, item.get('href', ''))['member'])

    if not candidates:
        for member in dict.fromkeys(marker_pages):
            document = package.xml(member)
            for node in document.iter():
                identifier = (node.get('id') or node.get(XML_ID) or '').casefold()
                if identifier in _COVER_IDS or 'cover' in node.get(EPUB + 'type', '').split():
                    images = {_target(member, image.get('src'))['member'] for image in node.iter()
                              if _local(image.tag) == 'img' and image.get('src')}
                    if len(images) != 1:
                        raise MediaUnavailable('The source cover marker is ambiguous.')
                    add(images.pop(), 'Explicit source cover marker')
    if not candidates:
        return None
    if len(candidates) != 1:
        raise MediaUnavailable('The source contains conflicting cover declarations.')
    member, evidence = next(iter(candidates.items()))
    return member, sorted(evidence)


def _thumbnail(data: bytes) -> bytes:
    _raster_type(data)
    try:
        with _DECODERS, warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(data), formats=('JPEG', 'PNG', 'GIF', 'WEBP')) as original:
                if original.width * original.height > MAX_PIXELS or max(original.size) > 20000:
                    raise MediaUnavailable('The cover exceeds the decoded image-size limit.')
                original.seek(0)
                original.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
                image = ImageOps.exif_transpose(original)
                image.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
                image = image.convert('RGBA' if 'A' in image.getbands() or 'transparency' in image.info else 'RGB')
                output = BytesIO()
                image.save(output, format='WEBP', quality=82, method=4)
                return output.getvalue()
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise MediaUnavailable('The cover could not be decoded safely.') from None


def _cache_path(library, work_id: str) -> Path | None:
    directory = library.state / 'covers'
    try:
        if directory.is_symlink() or directory.resolve().parent != library.state.resolve():
            return None
        directory.mkdir(parents=True, exist_ok=True)
        return directory / (hashlib.sha256(work_id.encode()).hexdigest() + '.json')
    except OSError:
        return None


def _read_cache(path: Path | None, fingerprint: str) -> tuple[bool, bytes | None]:
    if path is None:
        return False, None
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(fd, 'rb') as stream:
            raw = stream.read(MAX_CACHE_BYTES + 1)
        if len(raw) > MAX_CACHE_BYTES:
            return False, None
        record = json.loads(raw)
        if record.get('version') != CACHE_VERSION or record.get('fingerprint') != fingerprint:
            return False, None
        if record.get('image') is None:
            return True, None
        data = base64.b64decode(record['image'], validate=True)
        if _raster_type(data) != 'image/webp':
            return False, None
        return True, data
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return False, None


def _write_cache(path: Path | None, fingerprint: str, image: bytes | None, evidence: list[dict]):
    if path is None:
        return
    temporary = None
    try:
        record = {'version': CACHE_VERSION, 'fingerprint': fingerprint,
                  'image': base64.b64encode(image).decode() if image is not None else None, 'evidence': evidence}
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(record, stream, separators=(',', ':'))
        os.replace(temporary, path)
    except OSError:
        pass  # A read-only or full cache must never block catalog browsing.
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def load_cover(library, work_id: str) -> tuple[bytes, str]:
    """Return a bounded WebP thumbnail, or raise MediaUnavailable for fallback."""
    catalog = library._catalog()
    records = [(file_id, source) for file_id, source in catalog.get('files', {}).items()
               if source.get('work_id') == work_id and source.get('available')
               and Path(source.get('path', '')).suffix.lower() == '.epub']
    sources = [(file_id, *_current_source(library, file_id)) for file_id, _ in sorted(records)]
    fingerprint = hashlib.sha256(json.dumps([
        (file_id, str(path), source.get('sha256'), source['size'], source['mtime_ns'], source.get('extract_version'))
        for file_id, source, path in sources], separators=(',', ':')).encode()).hexdigest()
    cache_path = _cache_path(library, str(work_id))
    found, image = _read_cache(cache_path, fingerprint)
    if found:
        if image is None:
            raise MediaUnavailable('No unambiguous local cover is available for this book.')
        return image, 'image/webp'
    images, evidence = {}, []
    try:
        with _LOADERS:
            for file_id, source, path in sources:
                with _package(source, path) as package:
                    cover = _discover(package)
                    if cover is None:
                        continue
                    member, reasons = cover
                    data = package.read(member, MAX_IMAGE_BYTES)
                    _raster_type(data)
                    images[hashlib.sha256(data).hexdigest()] = data
                    evidence.append({'file_id': file_id, 'member': member, 'reasons': reasons})
                    if len(images) > 1:
                        raise MediaUnavailable('The local copies have conflicting cover images.')
            if len(images) != 1:
                raise MediaUnavailable('No unambiguous local cover is available for this book.')
            image = _thumbnail(next(iter(images.values())))
    except (MediaUnavailable, OSError, zipfile.BadZipFile, RuntimeError, NotImplementedError, ET.ParseError, zlib.error):
        _write_cache(cache_path, fingerprint, None, evidence)
        raise MediaUnavailable('No unambiguous local cover is available for this book.') from None
    _write_cache(cache_path, fingerprint, image, evidence)
    return image, 'image/webp'
