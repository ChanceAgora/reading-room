"""Bound disposable semantic generations without touching paid vectors or books."""
from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import re
from pathlib import Path

from .storage import read_json, writer

GENERATION = re.compile(r'sem_[0-9a-f]{20}')
SNAPSHOT = re.compile(r'[0-9a-f]{64}')
GENERATION_FILES = {'generation.json', 'index.usearch', 'windows.sqlite3'}


@contextlib.contextmanager
def semantic_reader(root):
    """Protect path opening as well as reads while old generations are pruned."""
    root.mkdir(parents=True, exist_ok=True)
    with (root / 'readers.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_SH)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _record(path):
    value = read_json(path, {})
    if not isinstance(value, dict):
        raise ValueError('Invalid semantic retention metadata.')
    return value


def _timestamp(value):
    parsed = dt.datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError('Semantic generation timestamp needs a timezone.')
    return parsed


def _plain(path, *, directory=False):
    return not path.is_symlink() and (path.is_dir() if directory else path.is_file())


def _plan(lib):
    root = lib.state / 'semantic'
    folders = [root, root / 'generations', root / 'snapshots']
    if any(not _plain(path, directory=True) for path in folders):
        raise ValueError('Semantic retention requires ordinary state directories.')
    if not _plain(root / 'current.json'):
        raise ValueError('Semantic retention requires a published current generation.')
    current = _record(root / 'current.json')
    active = current.get('generation', '')
    if not isinstance(active, str) or not GENERATION.fullmatch(active):
        raise ValueError('Invalid current semantic generation identity.')
    records = {}
    skipped = []
    uncertain_generation = False
    for folder in (root / 'generations').iterdir():
        # Only the three known generated files are ever eligible. Unknown,
        # incomplete, or symlinked directories are deliberately left alone.
        if (not GENERATION.fullmatch(folder.name) or not _plain(folder, directory=True)
                or {p.name for p in folder.iterdir()} != GENERATION_FILES
                or any(not _plain(folder / name) for name in GENERATION_FILES)):
            skipped.append(str(folder))
            uncertain_generation |= folder.is_dir() or folder.is_symlink()
            continue
        try:
            info = _record(folder / 'generation.json')
            if (info.get('generation') != folder.name
                    or not isinstance(info.get('snapshot_id'), str)
                    or not SNAPSHOT.fullmatch(info['snapshot_id'])
                    or info.get('index_file') != f'generations/{folder.name}/index.usearch'
                    or info.get('windows_file') != f'generations/{folder.name}/windows.sqlite3'):
                raise ValueError('Invalid generated file binding.')
            records[folder.name] = (info, _timestamp(info['built_at']))
        except (ValueError, KeyError, TypeError, OSError):
            skipped.append(str(folder))
            uncertain_generation = True
    if active not in records or any(current.get(k) != records[active][0].get(k)
                                    for k in ('snapshot_id', 'index_file', 'windows_file', 'built_at')):
        raise ValueError('Current semantic generation is incomplete or inconsistent; nothing pruned.')
    active_time = records[active][1]
    older = sorted((key for key, (_, stamp) in records.items()
                    if key != active and stamp <= active_time),
                   key=lambda key: (records[key][1], key), reverse=True)
    previous = current.get('previous_generation')
    if previous not in older:
        previous = older[0] if older else None
    keep = {active}
    if previous:
        keep.add(previous)
    # A newer uncommitted generation is not historical garbage.
    keep.update(key for key, (_, stamp) in records.items() if stamp > active_time)
    generation_paths = [root / 'generations' / key for key in older if key not in keep]
    snapshots = {info['snapshot_id'] for key, (info, _) in records.items() if key in keep}
    exact = lib._active().get('generation')
    snapshot_paths = []
    # If a generation could not be understood, do not guess whether its
    # snapshot is safe. Known old generations can still be reclaimed.
    if not uncertain_generation:
        for metadata in (root / 'snapshots').glob('*.json'):
            sid = metadata.stem
            database = metadata.with_suffix('.sqlite3')
            if not SNAPSHOT.fullmatch(sid) or not _plain(metadata) or not _plain(database):
                continue
            try:
                info = _record(metadata)
                if (info.get('snapshot_id') != sid or sid in snapshots
                        or info.get('exact_generation') == exact
                        or _timestamp(info['created_at']) > active_time):
                    continue
            except (ValueError, KeyError, TypeError, OSError):
                continue
            snapshot_paths.extend([metadata, database])
    paths = generation_paths + sorted(snapshot_paths)
    size = 0
    for path in paths:
        children = list(path.iterdir()) if path.is_dir() else [path]
        size += sum(child.stat().st_blocks * 512 for child in children)
    return {'current_generation': active, 'retained_generations': sorted(keep),
            'retained_snapshot_ids': sorted(snapshots), 'skipped_paths': skipped,
            'generation_paths': [str(p) for p in generation_paths],
            'snapshot_paths': [str(p) for p in sorted(snapshot_paths)],
            'reclaimable_bytes': size}


def prune_locked(lib, *, apply=False):
    """Caller holds semantic writer then library writer; active readers defer GC."""
    root = lib.state / 'semantic'
    with (root / 'readers.lock').open('a+') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'applied': False, 'deferred': 'Semantic readers are active.'}
        try:
            plan = _plan(lib)
            removed = []
            if apply:
                for name in plan['generation_paths']:
                    folder = Path(name)
                    # A flat, allowlisted directory avoids recursive deletion.
                    for filename in sorted(GENERATION_FILES):
                        (folder / filename).unlink()
                    folder.rmdir()
                    removed.append(name)
                for name in plan['snapshot_paths']:
                    Path(name).unlink()
                    removed.append(name)
            return {**plan, 'applied': apply, 'removed_paths': removed}
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def prune_semantic_state(lib, *, apply=False):
    """Dry run by default; take publication locks and reread all live pointers."""
    with writer(lib.state / 'semantic'):
        with writer(lib.state):
            return prune_locked(lib, apply=apply)
