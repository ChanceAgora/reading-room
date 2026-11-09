"""The publication audit checks staged bytes and modes, not a cleaned worktree."""
import importlib.util
import io
from pathlib import Path
import subprocess
import tarfile

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


def test_source_archive_cannot_silently_omit_skill_sources(audit, tmp_path, monkeypatch, capsys):
    skill = tmp_path / 'skills' / 'library-search' / 'SKILL.md'
    skill.parent.mkdir(parents=True)
    skill.write_text('The complete skill belongs in the source archive.')
    archive = tmp_path / 'source.tar.gz'
    for include_skill in (False, True):
        with tarfile.open(archive, 'w:gz') as tar:
            for name, data in [('README.md', b'Reading Room'), *([('skills/library-search/SKILL.md', skill.read_bytes())] if include_skill else [])]:
                member = tarfile.TarInfo('reading-room/' + name)
                member.size = len(data)
                tar.addfile(member, io.BytesIO(data))
        monkeypatch.setattr('sys.argv', ['check_public_release.py', '--archive', str(archive)])
        assert audit.main() == (0 if include_skill else 1)
        output = capsys.readouterr()
        if not include_skill:
            assert 'Source archive lacks skill file: skills/library-search/SKILL.md' in output.err
