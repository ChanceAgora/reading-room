from __future__ import annotations

import base64
import gzip
import json
import os
from pathlib import Path
import stat
from types import SimpleNamespace
import warnings
import zipfile

from fastapi.testclient import TestClient
from lxml import html
import pytest

from book_library.media import MediaUnavailable, describe_image, load_image
from book_library.web import create_app

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a2X8AAAAASUVORK5CYII=')
MEMBER = 'EPUB/images/figure.png'
ORIGIN = 'http://127.0.0.1:8765'


class MediaLibrary:
    def __init__(self, root, entries=None, *, member=MEMBER, alt='A source-provided tree description.'):
        self.root = root
        self.state = root / '.library'
        self.path = root / 'Book.epub'
        with zipfile.ZipFile(self.path, 'w', compression=zipfile.ZIP_DEFLATED) as z:
            for name, data in entries or [(MEMBER, PNG)]:
                z.writestr(name, data)
        current = self.path.stat()
        self.record = {'id': 'file-1', 'work_id': 'work-1', 'path': str(self.path), 'available': True, 'state': 'ready', 'size': current.st_size, 'mtime_ns': current.st_mtime_ns, 'cache': 'fixture.json.gz'}
        self.extraction = {'images': [{'member': member, 'alt_texts': [alt] if alt else [], 'referenced_by': [1], 'media_type': 'image/png'}], 'blocks': [{'ordinal': 1, 'kind': 'caption', 'text': 'Figure 1. A tree, according to the source.', 'image_refs': [member], 'locator': {'member': 'EPUB/chapter.xhtml', 'element_id': 'figure1'}}]}
        self.save_cache()

    def save_cache(self):
        p = self.state / 'extractions' / self.record['cache']
        p.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(p, 'wt') as f:
            json.dump(self.extraction, f)

    def _catalog(self):
        return {'files': {'file-1': self.record}}

    def read(self, passage_id, context=3):
        return {'passage': {'id': passage_id, 'work_id': 'work-1', 'title': 'A book', 'attribution': 'An author', 'location': 'A caption', 'text': 'Caption', 'limitations': []}, 'blocks': [{'id': 'block-1', 'kind': 'caption', 'text': 'Figure 1. A tree.', 'file_id': 'file-1', 'image_refs': [MEMBER], 'selected': True}], 'previous': None, 'next': None}


@pytest.fixture
def library(tmp_path):
    return MediaLibrary(tmp_path)


def test_source_descriptions_do_not_open_original_zip(library, monkeypatch):
    def no_zip(*args, **kwargs):
        raise AssertionError('Metadata lookup must not inflate source images.')
    monkeypatch.setattr(zipfile, 'ZipFile', no_zip)
    item = describe_image(library, 'file-1', MEMBER)
    assert item['alt'] == 'A source-provided tree description.'
    assert item['captions'] == ['Figure 1. A tree, according to the source.']


def test_loads_only_verified_raster_member_without_modifying_source(library):
    before = library.path.read_bytes()
    data, mime, info = load_image(library, 'file-1', MEMBER)
    assert data == PNG
    assert mime == 'image/png'
    assert info['member'] == MEMBER
    assert library.path.read_bytes() == before


@pytest.mark.parametrize('member', ['/etc/passwd', '../outside.png', 'EPUB/../image.png', 'https://example.com/image.png', 'C:/image.png', 'EPUB\\image.png', 'EPUB//image.png', 'EPUB/image\x00.png'])
def test_unsafe_paths_rejected_before_any_archive_read(library, monkeypatch, member):
    monkeypatch.setattr(zipfile, 'ZipFile', lambda *args, **kwargs: pytest.fail('No archive access expected'))
    with pytest.raises(MediaUnavailable):
        load_image(library, 'file-1', member)


def test_nonindexed_members_and_unknown_files_cannot_be_read(library, monkeypatch):
    monkeypatch.setattr(zipfile, 'ZipFile', lambda *args, **kwargs: pytest.fail('No archive access expected'))
    for fid, member in [('file-1', 'EPUB/private.xhtml'), ('file-other', MEMBER)]:
        with pytest.raises(MediaUnavailable):
            load_image(library, fid, member)
    library.extraction['blocks'][0]['image_refs'] = []
    library.save_cache()
    with pytest.raises(MediaUnavailable, match='verified source reference'):
        describe_image(library, 'file-1', MEMBER)


def test_stale_deleted_or_outside_sources_rejected(library, tmp_path, monkeypatch):
    monkeypatch.setattr(zipfile, 'ZipFile', lambda *args, **kwargs: pytest.fail('No archive access expected'))
    os.utime(library.path, ns=(library.record['mtime_ns'], library.record['mtime_ns'] + 1000))
    with pytest.raises(MediaUnavailable, match='changed'):
        load_image(library, 'file-1', MEMBER)
    library.path.unlink()
    with pytest.raises(MediaUnavailable, match='available'):
        load_image(library, 'file-1', MEMBER)
    library.record['path'] = str(tmp_path.parent / 'outside.epub')
    with pytest.raises(MediaUnavailable):
        load_image(library, 'file-1', MEMBER)


def test_source_and_cache_symlinks_rejected(library, tmp_path):
    original = library.path.with_name('Original.epub')
    library.path.rename(original)
    library.path.symlink_to(original)
    with pytest.raises(MediaUnavailable):
        describe_image(library, 'file-1', MEMBER)
    library.path.unlink()
    original.rename(library.path)
    cache = library.state / 'extractions' / library.record['cache']
    moved = cache.with_name('original.json.gz')
    cache.rename(moved)
    cache.symlink_to(moved)
    with pytest.raises(MediaUnavailable):
        describe_image(library, 'file-1', MEMBER)


def test_misleading_extension_cannot_execute_html_or_svg(tmp_path):
    lib = MediaLibrary(tmp_path, [(MEMBER, b'<svg xmlns="http://www.w3.org/2000/svg"><script>bad()</script></svg>')])
    with pytest.raises(MediaUnavailable, match='supported raster'):
        load_image(lib, 'file-1', MEMBER)


def test_magic_not_extension_or_publisher_mime_selects_raster_type(tmp_path):
    lib = MediaLibrary(tmp_path, [('EPUB/images/not-an-extension.bin', PNG)], member='EPUB/images/not-an-extension.bin')
    lib.extraction['images'][0]['media_type'] = 'text/html'
    lib.save_cache()
    assert load_image(lib, 'file-1', 'EPUB/images/not-an-extension.bin')[1] == 'image/png'


def test_expanded_image_size_is_bounded_before_read(tmp_path, monkeypatch):
    from book_library import media
    lib = MediaLibrary(tmp_path, [(MEMBER, PNG + b'x' * 1000)])
    monkeypatch.setattr(media, 'MAX_IMAGE_BYTES', 100)
    with pytest.raises(MediaUnavailable, match='viewing limit'):
        load_image(lib, 'file-1', MEMBER)


def test_duplicate_image_entries_and_zip_symlinks_rejected(tmp_path):
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)
        lib = MediaLibrary(tmp_path, [(MEMBER, PNG), (MEMBER, PNG)])
    with pytest.raises(MediaUnavailable, match='ambiguous'):
        load_image(lib, 'file-1', MEMBER)
    entry = zipfile.ZipInfo(MEMBER)
    entry.create_system = 3
    entry.external_attr = (stat.S_IFLNK | 0o777) << 16
    lib = MediaLibrary(tmp_path, [(entry, b'/outside')])
    with pytest.raises(MediaUnavailable, match='safely'):
        load_image(lib, 'file-1', MEMBER)


def test_unknown_description_is_explicit_and_source_text_remains_data(tmp_path):
    hostile = '<script src="https://bad.example/x">bad()</script>'
    lib = MediaLibrary(tmp_path, alt=hostile)
    with TestClient(create_app(lib), base_url=ORIGIN) as client:
        response = client.get('/api/ui/illustration/file-1', params={'member': MEMBER})
        assert response.status_code == 200
        data = response.json()['data']['illustration']
        assert data['alt'] == hostile
        assert data['description_status'] == 'source_provided'
        assert data['file_id'] == 'file-1' and data['member'] == MEMBER
        lib.extraction['images'][0]['alt_texts'] = []
        lib.save_cache()
        data = client.get('/api/ui/illustration/file-1', params={'member': MEMBER}).json()['data']['illustration']
        assert data['description_status'] == 'description_missing'


def test_image_endpoint_uses_nosniff_same_origin_raster_response(library):
    with TestClient(create_app(library), base_url=ORIGIN) as client:
        response = client.get('/image/file-1', params={'member': MEMBER})
        assert response.status_code == 200
        assert response.content == PNG
        assert response.headers['content-type'] == 'image/png'
        assert response.headers['x-content-type-options'] == 'nosniff'
        assert response.headers['cross-origin-resource-policy'] == 'same-origin'
        assert response.headers['cache-control'] == 'no-store'
        assert client.get('/image/file-1', params={'member': '../bad'}).status_code == 404
        assert client.get('/image/file-1', params={'member': MEMBER}, headers={'Host': 'evil.example'}).status_code == 400


def test_reading_view_links_illustrations_without_loading_any_media(library, monkeypatch):
    from book_library import media
    monkeypatch.setattr(media, 'load_image', lambda *args: pytest.fail('Reading prose must not open image bytes.'))
    monkeypatch.setattr(media, 'describe_image', lambda *args: pytest.fail('Reading prose uses already indexed references.'))
    with TestClient(create_app(library), base_url=ORIGIN) as client:
        response = client.get('/api/ui/read/passage-1')
        assert response.status_code == 200
        blocks = response.json()['data']['reading']['blocks']
        assert any(MEMBER in block.get('image_refs', []) for block in blocks)
