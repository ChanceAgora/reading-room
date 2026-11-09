"""Keep a queued intake's selected files from growing through folder inference.

The exact index discovers all local files and historically groups adjacent Word
parts. An intake must detect a new, unselected neighbor before that discovery
can enlarge its authorized review. These snapshots record selection, never an
ambient list of files that happened to be present when the worker started.
"""
from __future__ import annotations

from pathlib import Path


def capture_scope(lib, files, *, requested_path=None):
    """Describe the source selection without indexing or changing private state.

``files`` includes every already known part of the selected work. A selected
file monitors its immediate neighbors; an explicitly selected folder also
monitors descendants. Newly arrived neighbors never become allowed implicitly.
"""
    paths = sorted({str(Path(file['path']).expanduser().resolve()) for file in files})
    root = Path(lib.root).resolve()
    if not paths or any(root not in Path(path).parents for path in paths):
        raise ValueError('An intake scope needs selected files inside the library.')
    requested = Path(requested_path).expanduser().resolve() if requested_path is not None else None
    recursive_root = str(requested) if requested is not None and requested.is_dir() else None
    if requested is not None and requested != root and root not in requested.parents:
        raise ValueError('The requested intake scope must be inside the library.')
    return {'version': 1, 'allowed_paths': paths,
            'directories': sorted({str(Path(path).parent) for path in paths}),
            'recursive_root': recursive_root}


def scope_current(lib, job):
    """Whether no unselected book file has arrived in this intake's scope.

Missing or edited selected files are checked separately by the queue's source
fingerprints. Inventory uses the same alias and symlink rules as exact indexing.
An old queue record has no recursive selection to infer, so its selected files'
immediate parents provide a conservative, compatible fallback.
"""
    scope = job.get('source_scope')
    if scope is None:
        scope = capture_scope(lib, job['files'])
    if not isinstance(scope, dict) or scope.get('version') != 1:
        return False
    allowed = scope.get('allowed_paths')
    directories = scope.get('directories')
    if not isinstance(allowed, list) or not isinstance(directories, list):
        return False
    if not all(isinstance(path, str) for path in [*allowed, *directories]):
        return False
    recursive = scope.get('recursive_root')
    if recursive is not None and not isinstance(recursive, str):
        return False
    allowed, directories = set(allowed), set(directories)
    recursive = Path(recursive) if recursive else None
    try:
        for value in lib._inventory():
            path = Path(value)
            shares_scope = str(path.parent) in directories or recursive is not None and recursive in path.parents
            if shares_scope and value not in allowed:
                return False
    except (OSError, ValueError):
        return False
    return True
