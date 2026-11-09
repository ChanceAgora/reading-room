"""The publication audit checks staged bytes and modes, not a cleaned worktree."""
import importlib.util
from pathlib import Path
import subprocess

import pytest


@pytest.fixture
def audit(tmp_path, monkeypatch):
    source = Path(__file__).resolve().parents[1] / 'scripts/check_public_release.py'
    spec = importlib.util.spec_from_file_location('public_release_audit', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    subprocess.run(['git', 'init', '--quiet', str(tmp_path)], check=True)
    return module


def stage(audit, name):
    subprocess.run(['git', 'add', '--', name], cwd=audit.ROOT, check=True)


def test_staged_secret_cannot_be_hidden_by_clean_working_copy(audit):
    path = audit.ROOT / 'README.md'
    path.write_text('sk-' + 'x' * 40)
    stage(audit, 'README.md')
    path.write_text('Clean working copy')
    assert audit.check_index() == ['Private path or credential-shaped content: README.md']
    stage(audit, 'README.md')
    assert audit.check_index() == []


def test_staged_symlink_cannot_be_hidden_by_regular_working_file(audit):
    path = audit.ROOT / 'README.md'
    path.symlink_to('missing-target')
    stage(audit, 'README.md')
    path.unlink()
    path.write_text('A regular working file')
    assert audit.check_index() == ['Non-regular Git index entry: README.md']


def test_deleted_working_file_still_audits_staged_bytes(audit):
    path = audit.ROOT / 'README.md'
    path.write_text('Publishable content')
    stage(audit, 'README.md')
    path.unlink()
    assert audit.check_index() == []


def test_index_rejects_outside_allowlist_and_empty_selection(audit):
    assert audit.check_index() == ['No public files selected']
    (audit.ROOT / 'private.txt').write_text('Even harmless content stays excluded')
    stage(audit, 'private.txt')
    assert audit.check_index() == ['Outside public allowlist: private.txt']


@pytest.mark.parametrize('name', ['tests/.library/config.json', 'docs/reports/research.md',
                                  'frontend/src/.env.local', 'docs/books/notes.md'])
def test_private_state_is_excluded_even_inside_public_trees(audit, name):
    assert not audit.allowed(name)
    assert audit.allowed('.env.example')
