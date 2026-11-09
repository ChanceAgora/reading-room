"""Source-release smoke extraction never trusts archive paths or links."""
import importlib.util
import io
from pathlib import Path
import tarfile

import pytest


def smoke_module():
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'clean_install_smoke.py'
    spec = importlib.util.spec_from_file_location('clean_install_smoke', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_archive(path, entries):
    with tarfile.open(path, 'w:gz') as archive:
        for name, data in entries:
            entry = tarfile.TarInfo(name)
            entry.size = len(data)
            entry.mode = 0o755 if name.endswith('bin/setup') else 0o644
            archive.addfile(entry, io.BytesIO(data))


def test_source_archive_smoke_uses_single_root_with_spaces(tmp_path):
    archive = tmp_path / 'source.tar.gz'
    make_archive(archive, [('reading_room-0.1.0/bin/setup', b'#!/bin/sh\n'),
                           ('reading_room-0.1.0/pyproject.toml', b'[project]\n')])
    root = smoke_module().extract_checkout(archive, tmp_path)
    assert root == tmp_path / 'Clean source archive' / 'reading_room-0.1.0'
    assert (root / 'bin' / 'setup').stat().st_mode & 0o100


def test_source_archive_smoke_rejects_path_escape(tmp_path):
    archive = tmp_path / 'escape.tar.gz'
    make_archive(archive, [('../../escaped.txt', b'not allowed')])
    with pytest.raises(tarfile.FilterError):
        smoke_module().extract_checkout(archive, tmp_path)
    assert not (tmp_path / 'escaped.txt').exists()


def test_source_archive_smoke_rejects_links(tmp_path):
    archive = tmp_path / 'link.tar.gz'
    with tarfile.open(archive, 'w:gz') as writer:
        link = tarfile.TarInfo('root/link')
        link.type = tarfile.SYMTYPE
        link.linkname = '/private/data'
        writer.addfile(link)
    with pytest.raises(ValueError, match='regular files'):
        smoke_module().extract_checkout(archive, tmp_path)


def test_source_archive_smoke_rejects_multiple_roots(tmp_path):
    archive = tmp_path / 'roots.tar.gz'
    make_archive(archive, [('one/file', b'one'), ('two/file', b'two')])
    with pytest.raises(ValueError, match='exactly one'):
        smoke_module().extract_checkout(archive, tmp_path)
