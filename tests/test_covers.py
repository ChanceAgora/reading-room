from __future__ import annotations

from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import stat
import warnings
import zipfile

from PIL import Image
import pytest
from fastapi.testclient import TestClient

from book_library import covers
from book_library.media import MediaUnavailable, load_image
from book_library.web import create_app

CONTAINER = b'<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="EPUB/package.opf"/></rootfiles></container>'


def raster(color='navy', size=(600, 900), format='PNG'):
    out = BytesIO()
    Image.new('RGB', size, color).save(out, format=format)
    return out.getvalue()


def package(*, properties='cover-image', meta='', guide='', body=None, extra_items='', extras=(), image=None):
    manifest = '<item id="cover-image" href="images/cover.png" media-type="image/png" properties="' + properties + '"/>' + extra_items
    if body is not None:
        manifest += '<item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>'
    opf = '<package xmlns="http://www.idpf.org/2007/opf"><metadata>' + meta + '</metadata><manifest>' + manifest + '</manifest><spine>' + ('<itemref idref="chapter"/>' if body is not None else '') + '</spine><guide>' + guide + '</guide></package>'
    entries = [('META-INF/container.xml', CONTAINER), ('EPUB/package.opf', opf), ('EPUB/images/cover.png', image if image is not None else raster())]
    if body is not None:
        entries.append(('EPUB/chapter.xhtml', '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><body>' + body + '</body></html>'))
    return entries + list(extras)


class CoverLibrary:
    def __init__(self, root, entries=None):
        self.root = root
        self.state = root / '.library'
        self.path = root / 'Book.epub'
        self.files = {}
        self.write(entries if entries is not None else package())

    def write(self, entries, file_id='file-1', name='Book.epub'):
        path = self.root / name
        with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as z:
            for member, data in entries:
                z.writestr(member, data)
        current = path.stat()
        self.files[file_id] = {'id': file_id, 'work_id': 'work-1', 'path': str(path), 'available': True,
            'state': 'ready', 'size': current.st_size, 'mtime_ns': current.st_mtime_ns,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'extract_version': '2'}

    def _catalog(self):
        return {'files': self.files}


@pytest.fixture
def library(tmp_path):
    return CoverLibrary(tmp_path)


def assert_cover(library):
    data, mime = covers.load_cover(library, 'work-1')
    assert mime == 'image/webp'
    with Image.open(BytesIO(data)) as image:
        assert image.size == (192, 288)
    return data


def test_manifest_cover_becomes_small_raster_without_changing_original(library):
    original = library.path.read_bytes()
    assert_cover(library)
    assert library.path.read_bytes() == original
    record = json.loads(next((library.state / 'covers').glob('*.json')).read_text())
    assert record['evidence'][0]['member'] == 'EPUB/images/cover.png'
    assert record['evidence'][0]['reasons'] == ['EPUB cover-image declaration']
    # A cover declaration does not open this arbitrary member via /image.
    with pytest.raises(MediaUnavailable):
        load_image(library, 'file-1', 'EPUB/images/cover.png')


@pytest.mark.parametrize('kind', ['legacy', 'guide', 'guide-image', 'landmark', 'landmark-image', 'cover', 'cover_page', 'epub-type'])
def test_explicit_supported_cover_patterns(tmp_path, kind):
    kwargs = {'properties': ''}
    if kind == 'legacy':
        kwargs['meta'] = '<meta name="cover" content="cover-image"/>'
    elif kind == 'guide':
        kwargs.update(guide='<reference type="cover" href="chapter.xhtml#front"/>', body='<div id="front"><img src="images/cover.png"/></div>')
    elif kind == 'guide-image':
        kwargs['guide'] = '<reference type="coverpage" href="images/cover.png"/>'
    elif kind.startswith('landmark'):
        kwargs.update(body='<div id="front"><img src="images/cover.png"/></div>',
                      extra_items='<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
                      extras=[('EPUB/nav.xhtml', '<html xmlns:epub="http://www.idpf.org/2007/ops"><nav><a epub:type="cover" href="chapter.xhtml#front">Cover</a></nav></html>')])
        if kind == 'landmark-image':
            kwargs['extras'] = [('EPUB/nav.xhtml', kwargs['extras'][0][1].replace('chapter.xhtml#front', 'images/cover.png'))]
    else:
        marker = 'epub:type="cover"' if kind == 'epub-type' else 'id="' + kind + '"'
        kwargs['body'] = '<div ' + marker + '><img src="images/cover.png"/></div>'
    assert_cover(CoverLibrary(tmp_path, package(**kwargs)))


def test_identical_cover_alt_text_does_not_select_title_page(tmp_path):
    entries = package(properties='', body='<div id="cover_page"><img alt="[image: cover]" src="images/cover.png"/></div><div id="titlepage"><img alt="[image: cover]" src="images/title.png"/></div>', extras=[('EPUB/images/title.png', raster('red'))])
    lib = CoverLibrary(tmp_path, entries)
    assert_cover(lib)
    record = json.loads(next((lib.state / 'covers').glob('*.json')).read_text())
    assert record['evidence'][0]['member'] == 'EPUB/images/cover.png'


@pytest.mark.parametrize('body', ['<img alt="cover" src="images/cover.png"/>', '<img src="images/cover.png"/>', '<div id="cover"><img src="images/cover.png"/><img src="images/another.png"/></div>'])
def test_ordinary_first_images_alt_text_and_ambiguous_markers_do_not_authorize_cover(tmp_path, body):
    lib = CoverLibrary(tmp_path, package(properties='', body=body))
    with pytest.raises(MediaUnavailable):
        covers.load_cover(lib, 'work-1')


def test_conflicting_explicit_declarations_produce_fallback(tmp_path):
    lib = CoverLibrary(tmp_path, package(meta='<meta name="cover" content="other"/>',
        extra_items='<item id="other" href="images/another.png" media-type="image/png"/>',
        extras=[('EPUB/images/another.png', raster('red'))]))
    with pytest.raises(MediaUnavailable):
        covers.load_cover(lib, 'work-1')


@pytest.mark.parametrize('href', ['../../../outside.png', '/absolute.png', 'https://example.com/image.png', 'images/%2e%2e/%2e%2e/%2e%2e/outside.png', 'images/cover.svg', 'images/missing.png'])
def test_invalid_or_unsupported_declared_cover_target_falls_back(tmp_path, href):
    entries = package()
    entries[1] = (entries[1][0], entries[1][1].replace('href="images/cover.png"', 'href="' + href + '"'))
    entries.append(('EPUB/images/cover.svg', '<svg/>'))
    lib = CoverLibrary(tmp_path, entries)
    with pytest.raises(MediaUnavailable):
        covers.load_cover(lib, 'work-1')


def test_unrelated_external_manifest_item_does_not_block_local_cover(tmp_path):
    lib = CoverLibrary(tmp_path, package(guide='<reference type="cover" href="images/cover.png"/>', extra_items='<item id="remote" href="https://example.com/style.css" media-type="text/css"/>'))
    assert_cover(lib)


def test_positive_cache_avoids_archive_access_but_checks_source_freshness(library, monkeypatch):
    expected = assert_cover(library)
    monkeypatch.setattr(zipfile, 'ZipFile', lambda *a, **kw: pytest.fail('Cached cover must not reopen an archive'))
    assert covers.load_cover(library, 'work-1')[0] == expected
    record = library.files['file-1']
    os.utime(library.path, ns=(record['mtime_ns'], record['mtime_ns'] + 1000))
    with pytest.raises(MediaUnavailable):
        covers.load_cover(library, 'work-1')


def test_missing_cover_is_negatively_cached(tmp_path, monkeypatch):
    lib = CoverLibrary(tmp_path, package(properties=''))
    with pytest.raises(MediaUnavailable):
        covers.load_cover(lib, 'work-1')
    monkeypatch.setattr(zipfile, 'ZipFile', lambda *a, **kw: pytest.fail('Cached absence must not reopen an archive'))
    with pytest.raises(MediaUnavailable):
        covers.load_cover(lib, 'work-1')


def test_updated_source_invalidates_positive_and_negative_cache(library):
    original = assert_cover(library)
    library.write(package(image=raster('red')))
    assert assert_cover(library) != original
    library.write(package(properties=''))
    with pytest.raises(MediaUnavailable):
        covers.load_cover(library, 'work-1')
    library.write(package())
    assert assert_cover(library) == original


def test_deleted_source_does_not_serve_a_cached_thumbnail(library):
    assert_cover(library)
    library.path.unlink()
    with pytest.raises(MediaUnavailable):
        covers.load_cover(library, 'work-1')


def test_source_symlink_and_outside_library_are_rejected(library):
    original = library.path.with_name('Original.epub')
    library.path.rename(original)
    library.path.symlink_to(original)
    with pytest.raises(MediaUnavailable):
        covers.load_cover(library, 'work-1')
    library.files['file-1']['path'] = str(library.root.parent / 'outside.epub')
    with pytest.raises(MediaUnavailable):
        covers.load_cover(library, 'work-1')


def test_symlinked_cache_directory_is_not_followed(library, tmp_path):
    elsewhere = tmp_path / 'elsewhere'
    elsewhere.mkdir()
    library.state.mkdir()
    (library.state / 'covers').symlink_to(elsewhere, target_is_directory=True)
    assert_cover(library)
    assert not list(elsewhere.iterdir())


def test_corrupt_cache_cannot_serve_active_content(library):
    expected = assert_cover(library)
    path = next((library.state / 'covers').glob('*.json'))
    record = json.loads(path.read_text())
    import base64
    record['image'] = base64.b64encode(b'<script>bad()</script>').decode()
    path.write_text(json.dumps(record))
    assert assert_cover(library) == expected


def test_docx_has_no_assumed_cover(tmp_path):
    lib = CoverLibrary(tmp_path)
    lib.files['file-1']['path'] = str(tmp_path / 'Book.docx')
    with pytest.raises(MediaUnavailable):
        covers.load_cover(lib, 'work-1')


@pytest.mark.parametrize('image', [b'<html>Not an image</html>', b'\x89PNG\r\n\x1a\n' + b'0' * 40])
def test_malformed_or_mislabelled_images_fail_safely(tmp_path, image):
    lib = CoverLibrary(tmp_path, package(image=image))
    with pytest.raises(MediaUnavailable):
        covers.load_cover(lib, 'work-1')


def test_image_byte_and_decoded_pixel_limits(tmp_path, monkeypatch):
    lib = CoverLibrary(tmp_path)
    monkeypatch.setattr(covers, 'MAX_IMAGE_BYTES', 10)
    with pytest.raises(MediaUnavailable):
        covers.load_cover(lib, 'work-1')
    monkeypatch.setattr(covers, 'MAX_IMAGE_BYTES', 20 * 1024 * 1024)
    monkeypatch.setattr(covers, 'MAX_PIXELS', 100)
    lib.write(package(image=raster('red')))
    with pytest.raises(MediaUnavailable):
        covers.load_cover(lib, 'work-1')


def test_xml_entity_declarations_are_rejected(tmp_path):
    entries = package()
    entries[0] = (entries[0][0], b'<!DOCTYPE container [<!ENTITY x "oops">]>' + CONTAINER)
    with pytest.raises(MediaUnavailable):
        covers.load_cover(CoverLibrary(tmp_path, entries), 'work-1')


def test_duplicate_archive_members_and_member_symlinks_are_rejected(tmp_path):
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)
        lib = CoverLibrary(tmp_path, package(extras=[('EPUB/images/cover.png', raster())]))
    with pytest.raises(MediaUnavailable):
        covers.load_cover(lib, 'work-1')
    entries = package()
    entry = zipfile.ZipInfo('EPUB/images/cover.png')
    entry.create_system = 3
    entry.external_attr = (stat.S_IFLNK | 0o777) << 16
    entries[2] = (entry, b'/outside')
    lib.write(entries)
    with pytest.raises(MediaUnavailable):
        covers.load_cover(lib, 'work-1')


def test_different_cover_images_across_local_editions_are_not_guessed(library):
    library.write(package(image=raster('red')), file_id='file-2', name='Another.epub')
    with pytest.raises(MediaUnavailable):
        covers.load_cover(library, 'work-1')


def test_same_cover_in_duplicate_local_copies_is_unambiguous(library):
    library.write(package(), file_id='file-2', name='Another.epub')
    assert_cover(library)


@pytest.mark.parametrize('format', ['JPEG', 'GIF', 'WEBP'])
def test_other_safe_raster_formats_get_reencoded_as_webp(tmp_path, format):
    assert_cover(CoverLibrary(tmp_path, package(image=raster(format=format))))


def test_utf16_entity_declarations_are_also_rejected(tmp_path):
    entries = package()
    xml = '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE container [<!ENTITY x "oops">]>' + CONTAINER.decode()
    entries[0] = (entries[0][0], xml.encode('utf-16'))
    with pytest.raises(MediaUnavailable):
        covers.load_cover(CoverLibrary(tmp_path, entries), 'work-1')


def test_endpoint_returns_only_same_origin_safe_thumbnail_and_missing_fallback(library):
    with TestClient(create_app(library), base_url='http://127.0.0.1:8765') as client:
        response = client.get('/covers/work-1')
        assert response.status_code == 200
        assert response.headers['content-type'] == 'image/webp'
        assert response.headers['x-content-type-options'] == 'nosniff'
        assert response.headers['cross-origin-resource-policy'] == 'same-origin'
        assert response.headers['cache-control'] == 'no-store'
        assert client.get('/covers/missing').status_code == 404
        assert client.get('/covers/work-1', headers={'Host': 'evil.example'}).status_code == 400
