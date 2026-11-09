"""Retention removes only historical generated state and preserves recovery."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from book_library import semantic_library as sem
from book_library.semantic_retention import prune_semantic_state, semantic_reader
from book_library.storage import atomic_json
from test_semantic_library import approve, library


def generation(lib, number, *, exact=None):
    root = lib.state / 'semantic'
    name = f'sem_{number:020x}'
    snapshot = f'{number:064x}'
    folder = root / 'generations' / name
    folder.mkdir(parents=True)
    (root / 'snapshots').mkdir(exist_ok=True)
    info = {'generation': name, 'snapshot_id': snapshot,
            'exact_generation': exact or f'exact-{number}',
            'index_file': f'generations/{name}/index.usearch',
            'windows_file': f'generations/{name}/windows.sqlite3',
            'built_at': f'2026-11-{number:02d}T12:00:00+00:00',
            'created_at': f'2026-11-{number:02d}T11:00:00+00:00'}
    atomic_json(folder / 'generation.json', info)
    (folder / 'index.usearch').write_bytes(b'index')
    (folder / 'windows.sqlite3').write_bytes(b'windows')
    atomic_json(root / 'snapshots' / f'{snapshot}.json', info)
    (root / 'snapshots' / f'{snapshot}.sqlite3').write_bytes(b'snapshot')
    return info


@pytest.fixture
def state(tmp_path):
    lib = SimpleNamespace(state=tmp_path / '.library', _active=lambda: {'generation': 'exact-4'})
    entries = [generation(lib, n) for n in range(1, 5)]
    atomic_json(lib.state / 'semantic' / 'current.json', entries[-1])
    return lib, entries


def test_dry_run_then_prune_preserves_current_rollback_and_durable_state(state):
    lib, entries = state
    durable = ['semantic/cache/paid.sqlite3', 'pilot/frozen.json', 'curation.jsonl',
               'usage.jsonl', 'passage-history.sqlite3', 'section-identities.json']
    for name in durable:
        path = lib.state / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'keep unchanged')
    plan = prune_semantic_state(lib)
    assert plan['retained_generations'] == [row['generation'] for row in entries[-2:]]
    assert len(plan['generation_paths']) == 2 and len(plan['snapshot_paths']) == 4
    assert len(list((lib.state / 'semantic/generations').iterdir())) == 4
    result = prune_semantic_state(lib, apply=True)
    assert result['applied'] and len(result['removed_paths']) == 6
    assert sorted(p.name for p in (lib.state / 'semantic/generations').iterdir()) == plan['retained_generations']
    assert len(list((lib.state / 'semantic/snapshots').iterdir())) == 4
    assert all((lib.state / name).read_bytes() == b'keep unchanged' for name in durable)
    assert prune_semantic_state(lib, apply=True)['removed_paths'] == []


def test_active_reader_defers_deletion(state):
    lib, _ = state
    with semantic_reader(lib.state / 'semantic'):
        result = prune_semantic_state(lib, apply=True)
    assert not result['applied'] and 'readers' in result['deferred']
    assert len(list((lib.state / 'semantic/generations').iterdir())) == 4


def test_finder_metadata_does_not_disable_snapshot_cleanup(state):
    lib, _ = state
    metadata = lib.state / 'semantic/generations/.DS_Store'
    metadata.write_bytes(b'finder state')
    result = prune_semantic_state(lib, apply=True)
    assert str(metadata) in result['skipped_paths']
    assert metadata.read_bytes() == b'finder state'
    assert len(list((lib.state / 'semantic/snapshots').iterdir())) == 4


def test_symlinked_or_unknown_generation_is_never_deleted(state, tmp_path):
    lib, entries = state
    oldest = lib.state / 'semantic/generations' / entries[0]['generation']
    target = tmp_path / 'important-source'
    target.write_bytes(b'original')
    (oldest / 'index.usearch').unlink()
    (oldest / 'index.usearch').symlink_to(target)
    result = prune_semantic_state(lib, apply=True)
    assert str(oldest) in result['skipped_paths']
    assert oldest.exists() and target.read_bytes() == b'original'
    assert len(list((lib.state / 'semantic/snapshots').iterdir())) == 8


def test_invalid_current_aborts_before_deleting_anything(state):
    lib, entries = state
    current = {**entries[-1], 'windows_file': '../elsewhere.sqlite3'}
    atomic_json(lib.state / 'semantic/current.json', current)
    with pytest.raises(ValueError, match='inconsistent'):
        prune_semantic_state(lib, apply=True)
    assert len(list((lib.state / 'semantic/generations').iterdir())) == 4


def test_pending_exact_snapshot_and_newer_unpublished_generation_are_preserved(state):
    lib, entries = state
    newer = generation(lib, 5, exact='pending-exact')
    lib._active = lambda: {'generation': 'exact-1'}
    result = prune_semantic_state(lib, apply=True)
    assert newer['generation'] in result['retained_generations']
    assert (lib.state / 'semantic/snapshots' / (entries[0]['snapshot_id'] + '.sqlite3')).exists()


def test_successful_rebuilds_bound_history_without_reembedding(library):
    lib, _, calls, _ = library
    approve(lib)
    built = []
    for number in range(4):
        if number:
            lib.annotate(lib.books()[0]['id'], {'field': 'notes', 'value': f'Note {number}',
                         'evidence': 'Test review', 'origin': 'user', 'status': 'confirmed'})
            lib.sync(semantic=False)
        built.append(sem.build_index(lib))
    assert len(calls) == 1
    root = lib.state / 'semantic'
    assert sorted(p.name for p in (root / 'generations').iterdir()) == sorted(row['generation'] for row in built[-2:])
    assert sorted(p.stem for p in (root / 'snapshots').glob('*.json')) == sorted(row['snapshot_id'] for row in built[-2:])
    assert built[-1]['previous_generation'] == built[-2]['generation']
    assert built[-1]['retention']['applied']
    assert sem.search(lib, 'river memory')
    assert sem.status(lib)['state'] == 'ready'


def test_unchanged_sync_retries_cleanup_deferred_by_a_reader(library):
    lib, _, calls, _ = library
    approve(lib)
    root = lib.state / 'semantic'
    built = [sem.build_index(lib), sem.build_index(lib, force=True)]
    with semantic_reader(root):
        third = sem.build_index(lib, force=True)
    assert not third['retention']['applied']
    assert len(list((root / 'generations').iterdir())) == 3
    result = sem.build_index(lib)
    assert not result['changed'] and result['retention']['applied']
    assert sorted(p.name for p in (root / 'generations').iterdir()) == sorted([built[-1]['generation'], third['generation']])
    assert len(calls) == 1


def test_failed_publication_keeps_prior_generations_snapshots_and_cached_vectors(library, monkeypatch):
    lib, _, _, _ = library
    approve(lib)
    built = [sem.build_index(lib), sem.build_index(lib, force=True)]
    root = lib.state / 'semantic'
    cached_files = [path for path in (root / 'cache').rglob('*') if path.is_file()]
    write = sem.atomic_json

    def fail_publication(path, value):
        if path == root / 'current.json':
            raise OSError('Simulated publication failure')
        return write(path, value)

    monkeypatch.setattr(sem, 'atomic_json', fail_publication)
    with pytest.raises(OSError, match='publication failure'):
        sem.build_index(lib, force=True)
    for info in built:
        assert (root / info['index_file']).exists()
        assert (root / 'snapshots' / (info['snapshot_id'] + '.sqlite3')).exists()
    assert all(path.exists() for path in cached_files)
    assert sem._current(lib)['generation'] == built[-1]['generation']
