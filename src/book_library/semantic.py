"""Shared embedding adapters and resumable frozen-pilot utilities.

Semantic preparation has its own serialized cache writer; publishing a completed
index also takes the shared library writer. API accounting takes that shared lock
only around ledger writes, so embedding never deadlocks inside a reservation.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shlex
import tempfile
import time
from pathlib import Path

import numpy as np

from .budget import Budget
from .storage import atomic_json, read_json, writer

LOCAL_MODEL = 'intfloat/multilingual-e5-small'
OPENAI_MODEL = 'text-embedding-3-large'
LOCAL_DIMENSIONS = 384
OPENAI_DIMENSIONS = 3072
CACHE_VERSION = 2
_MODEL = None
_LOCAL_REVISION = None


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _snapshot_revision(path):
    if not isinstance(path, (str, Path)):
        return None
    parts = Path(path).parts
    for i, part in enumerate(parts[:-1]):
        if part == 'snapshots' and re.fullmatch(r'[a-f0-9]{40,64}', parts[i + 1]):
            return parts[i + 1]
    return None


def local_model():
    global _MODEL, _LOCAL_REVISION
    if _MODEL is None:
        import torch
        from huggingface_hub import try_to_load_from_cache
        from sentence_transformers import SentenceTransformer

        torch.set_num_threads(6)
        # Pin to the cached revision when present; otherwise resolve the snapshot
        # after the initial model download. Never accept a null revision in reports.
        cached = try_to_load_from_cache(LOCAL_MODEL, 'config.json')
        revision = _snapshot_revision(cached)
        options = {'revision': revision} if revision else {}
        _MODEL = SentenceTransformer(LOCAL_MODEL, device='mps' if torch.backends.mps.is_available() else 'cpu', trust_remote_code=False, **options)
        _MODEL.max_seq_length = 512
        _LOCAL_REVISION = revision or _snapshot_revision(try_to_load_from_cache(LOCAL_MODEL, 'config.json'))
        if not _LOCAL_REVISION:
            _MODEL = None
            raise ValueError('Could not establish the local model snapshot revision; do not run an unpinned pilot.')
    return _MODEL


def local_revision():
    local_model()
    if not _LOCAL_REVISION:
        raise ValueError('Local model snapshot revision unavailable.')
    return _LOCAL_REVISION


def embedding_config(engine):
    if engine not in ('local', 'openai'):
        raise ValueError('Unknown pilot engine.')
    return {
        'cache_version': CACHE_VERSION,
        'engine': engine,
        'model': LOCAL_MODEL if engine == 'local' else OPENAI_MODEL,
        'model_revision': local_revision() if engine == 'local' else OPENAI_MODEL,
        'dimensions': LOCAL_DIMENSIONS if engine == 'local' else OPENAI_DIMENSIONS,
        'normalization': 'unit-l2',
        'metric': 'cos',
        'passage_prefix': 'passage: ' if engine == 'local' else '',
        'query_prefix': 'query: ' if engine == 'local' else '',
        'window_tokenizer': LOCAL_MODEL,
        'window_tokenizer_revision': local_revision(),
        'window_max_tokens': 512,
    }


def _texts(texts):
    if not isinstance(texts, (list, tuple)) or not texts or any(not isinstance(t, str) or not t.strip() for t in texts):
        raise ValueError('Embedding inputs must be nonempty text strings.')
    return list(texts)


def _validate_vectors(value, rows, dimensions):
    vector = np.asarray(value, dtype=np.float32)
    if vector.shape != (rows, dimensions):
        raise ValueError(f'Embedding shape mismatch: expected {rows} by {dimensions}.')
    if not np.isfinite(vector).all():
        raise ValueError('Embedding vectors must contain only finite values.')
    lengths = np.linalg.norm(vector, axis=1)
    if np.any(lengths <= 0):
        raise ValueError('Embedding vectors must have nonzero length.')
    return np.ascontiguousarray(vector / lengths[:, None], dtype=np.float32)


def _check_local_limit(texts, kind):
    tokenizer = local_model().tokenizer
    for text in texts:
        if len(tokenizer(kind + ': ' + text)['input_ids']) > 512:
            raise ValueError('Window exceeds the local model’s 512-token limit; never silently truncate.')


def embed_local(texts, kind='passage', batch_size=32):
    if kind not in ('passage', 'query'):
        raise ValueError('Embedding kind must be passage or query.')
    texts = _texts(texts)
    _check_local_limit(texts, kind)
    matrix = local_model().encode([kind + ': ' + t for t in texts], batch_size=batch_size, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False)
    return _validate_vectors(matrix, len(texts), LOCAL_DIMENSIONS)


def api_key(state=None):
    """Read only the existing authorized key; never copy credentials to library state."""
    value = os.environ.get('OPENAI_API_KEY', '').strip()
    if value:
        return value
    env_path = os.environ.get('LIBRARY_OPENAI_ENV') or (read_json(state / 'config.json', {}).get('openai_env_file') if state else None)
    if env_path:
        try:
            lines = Path(env_path).expanduser().read_text().splitlines()
        except OSError:
            raise ValueError('The configured existing OpenAI credential file cannot be read.') from None
        for line in lines:
            line = line.strip()
            if line.startswith('export '):
                line = line[7:].lstrip()
            name, sep, val = line.partition('=')
            if sep and name.strip() == 'OPENAI_API_KEY':
                try:
                    values = shlex.split(val, comments=True, posix=True)
                except ValueError:
                    raise ValueError('The existing OpenAI credential assignment is malformed.') from None
                if len(values) == 1 and values[0].strip():
                    return values[0]
                break
    raise ValueError('Existing OpenAI key unavailable. Configure a reference to the authorized existing env file; never put keys in reports.')


def _exception_types(exc):
    """Bounded transport diagnostics without provider messages or request data."""
    names = []; seen = set()
    while exc is not None and id(exc) not in seen and len(names) < 5:
        seen.add(id(exc)); names.append(type(exc).__name__)
        exc = exc.__cause__ or (None if exc.__suppress_context__ else exc.__context__)
    return ' -> '.join(names)


def _authorize_openai_request(state, scope):
    if scope not in ('pilot', 'initial', 'monthly'):
        raise ValueError('Unknown semantic budget scope.')
    approved = read_json(state / 'config.json', {}).get('semantic', {})
    initial_approved = bool(approved.get('enabled') and approved.get('full_build_approved') and approved.get('engine') == 'openai')
    if scope in ('initial', 'monthly') and not initial_approved:
        raise ValueError('OpenAI semantic requests await explicit OpenAI authorization and an enabled engine.')
    if scope != 'pilot':
        from .public_config import require_budget
        require_budget(state)
    return initial_approved


def embed_openai(state, texts, scope='pilot'):
    from openai import OpenAI
    import tiktoken

    texts = _texts(texts)
    _authorize_openai_request(state, scope)
    encoding = tiktoken.get_encoding('cl100k_base')
    counts = [len(encoding.encode(t, disallowed_special=())) for t in texts]
    if max(counts) > 8192 or sum(counts) > 300_000:
        raise ValueError('Embedding request exceeds the API input limits; split the batch first.')
    client = OpenAI(api_key=api_key(state), base_url='https://api.openai.com/v1', max_retries=0, timeout=90)
    try:
        # Tokenization and client preparation can outlive a user's disable
        # action. Recheck at the request/reservation boundary as well.
        initial_approved = _authorize_openai_request(state, scope)
        budget = Budget(state)
        # Reserve before every actual attempt. No hidden SDK retries can escape it.
        reservation = budget.reserve(int(sum(counts) * 1.05) + len(texts) * 2, scope, initial_approved=initial_approved)
        try:
            # Omitting encoding_format lets the SDK request compact base64 and
            # decode it to floats before our unchanged shape/row/finite checks.
            response = client.embeddings.create(model=OPENAI_MODEL, dimensions=OPENAI_DIMENSIONS, input=texts)
        except Exception as exc:
            # Timeouts may be billable; never echo provider messages, request
            # bodies, URLs, headers, or credential fragments from their causes.
            raise RuntimeError(f'OpenAI embedding request failed ({_exception_types(exc)}); its reservation is retained. Exact search remains available.') from None
        budget.settle(reservation, response.usage.total_tokens)
    finally:
        try:
            client.close()
        except Exception as exc:
            # Cleanup must not replace the original failure or discard a paid,
            # successful response. Record only the safe exception class name.
            logging.getLogger(__name__).warning('OpenAI client cleanup failed (%s).', type(exc).__name__)
    data = sorted(response.data, key=lambda d: d.index)
    if [d.index for d in data] != list(range(len(texts))):
        raise ValueError('OpenAI embedding response has missing or duplicate rows; recorded usage is retained.')
    return _validate_vectors([d.embedding for d in data], len(texts), OPENAI_DIMENSIONS)


def _save_vectors(path, vectors):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            np.save(stream, vectors, allow_pickle=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _load_vectors(path, rows, dimensions):
    try:
        return _validate_vectors(np.load(path, allow_pickle=False), rows, dimensions)
    except (OSError, ValueError, EOFError):
        raise ValueError('An embedding cache is invalid; repair the identified cache before retrying paid processing: ' + str(path)) from None


def _validate_manifest(lib, windows=None):
    pilot = lib.state / 'pilot'
    manifest = read_json(pilot / 'manifest.json')
    if not manifest or manifest.get('frozen') is not True:
        raise ValueError('Freeze the pilot corpus and judgments before embedding.')
    queries = read_json(pilot / 'queries.json')
    if manifest.get('query_count') != 24 or not isinstance(queries, list) or len(queries) != 24 or canonical_hash(queries) != manifest.get('queries_sha256'):
        raise ValueError('The frozen 24-query pilot judgments are missing or changed.')
    allowed = set(manifest.get('work_ids', []))
    if len(allowed) != 12 or len(manifest.get('work_ids', [])) != 12:
        raise ValueError('Pilot must contain exactly its authorized twelve books.')
    persisted = read_json(pilot / 'windows.json')
    if not isinstance(persisted, list) or not persisted or canonical_hash(persisted) != manifest.get('windows_sha256'):
        raise ValueError('Pilot windows changed after freeze.')
    if windows is not None and canonical_hash(windows) != manifest['windows_sha256']:
        raise ValueError('Supplied windows differ from the frozen pilot.')
    windows = persisted
    if {w.get('work_id') for w in windows} != allowed or len({w.get('id') for w in windows}) != len(windows):
        raise ValueError('Pilot windows must cover exactly the twelve frozen books with unique IDs.')
    if not manifest.get('tokenizer_revision'):
        raise ValueError('The pilot must record a pinned tokenizer revision.')
    return manifest, windows


def _validate_sources(lib, manifest):
    """Do not send an outdated or silently expanded corpus after the freeze."""
    catalog = lib._catalog()
    for file_id, source_hash in manifest.get('source_hashes', {}).items():
        source = catalog['files'].get(file_id)
        if not source or source.get('sha256') != source_hash or not source.get('available') or source.get('state') != 'ready':
            raise ValueError('Frozen pilot source changed or is unavailable; review and refreeze before embedding.')
        try:
            stat = Path(source['path']).stat()
        except OSError:
            raise ValueError('Frozen pilot source is unavailable; synchronize and review before embedding.') from None
        if stat.st_size != source['size'] or stat.st_mtime_ns != source['mtime_ns']:
            raise ValueError('Frozen pilot source changed after indexing; synchronize and review before embedding.')


def build_engine(lib, engine, windows):
    """Build only frozen pilot windows; resume atomic, content-bound batch caches."""
    if engine not in ('local', 'openai'):
        raise ValueError('Unknown pilot engine.')
    started = time.perf_counter()
    pilot = lib.state / 'pilot'
    with writer(pilot):
        manifest, windows = _validate_manifest(lib, windows)
        _validate_sources(lib, manifest)
        config = embedding_config(engine)
        if manifest['tokenizer_revision'] != config['window_tokenizer_revision']:
            raise ValueError('Current tokenizer differs from the frozen pilot revision.')
        _check_local_limit([w['text'] for w in windows], 'passage')
        fingerprint = canonical_hash({'config': config, 'manifest': manifest})
        folder = pilot / engine
        folder.mkdir(exist_ok=True)
        build_folder = folder / 'builds' / fingerprint
        build_folder.mkdir(parents=True, exist_ok=True)
        before = Budget(lib.state).report()
        vectors = []
        batch_size = 64 if engine == 'openai' else 128
        cached_batches = embedded_batches = 0
        for offset in range(0, len(windows), batch_size):
            part = windows[offset:offset + batch_size]
            batch_hash = canonical_hash({'binding': fingerprint, 'offset': offset, 'windows': part})
            path = build_folder / ('batch-' + batch_hash + '.npy')
            if path.exists():
                vec = _load_vectors(path, len(part), config['dimensions'])
                cached_batches += 1
            else:
                vec = embed_local([w['text'] for w in part]) if engine == 'local' else embed_openai(lib.state, [w['text'] for w in part], scope='pilot')
                vec = _validate_vectors(vec, len(part), config['dimensions'])
                _save_vectors(path, vec)
                embedded_batches += 1
            vectors.append(vec)
        matrix = np.vstack(vectors)
        from usearch.index import Index

        index = Index(ndim=config['dimensions'], metric='cos', dtype='f32', connectivity=16, expansion_add=128, expansion_search=128)
        index.add(np.arange(len(matrix), dtype=np.uint64), matrix, threads=6)
        temporary_index = build_folder / 'index.pending'
        index.save(str(temporary_index))
        os.replace(temporary_index, build_folder / 'index.usearch')
        after = Budget(lib.state).report()
        info = {
            **config, 'windows': len(windows), 'coverage_books': 12, 'scope': 'pilot only',
            'seconds': time.perf_counter() - started,
            'cached_batches': cached_batches, 'embedded_batches': embedded_batches,
            'manifest_hash': canonical_hash(manifest), 'windows_sha256': manifest['windows_sha256'],
            'queries_sha256': manifest['queries_sha256'], 'generation': manifest['generation'],
            'cache_fingerprint': fingerprint, 'index_file': str((build_folder / 'index.usearch').relative_to(folder)),
            'api_usage': {
                'requests': after['requests'] - before['requests'],
                'actual_tokens': after['actual_tokens'] - before['actual_tokens'],
                'pilot_dollars_spent_or_reserved': after['spent_or_reserved']['pilot'] - before['spent_or_reserved']['pilot'],
            },
        }
        # Revalidate after expensive work; readers only see the previous complete
        # engine or this complete one. They never see an index with mismatched IDs.
        with writer(lib.state):
            latest, _ = _validate_manifest(lib, windows)
            if canonical_hash(latest) != info['manifest_hash']:
                raise ValueError('Pilot manifest changed while building; previous index remains active.')
            _validate_sources(lib, latest)
            atomic_json(build_folder / 'engine.json', info)
            atomic_json(folder / 'engine.json', info)
        return info


def semantic_search(lib, query, engine, limit=60, scope='monthly'):
    if engine not in ('local', 'openai'):
        raise ValueError('Unknown pilot engine.')
    if scope not in ('pilot', 'monthly'):
        raise ValueError('Query budget scope must be pilot or monthly.')
    _texts([query])
    pilot = lib.state / 'pilot'
    with writer(pilot):
        manifest, windows = _validate_manifest(lib)
        folder = pilot / engine
        info = read_json(folder / 'engine.json')
        if not info:
            raise ValueError('That pilot engine has not been built.')
        if info.get('manifest_hash') != canonical_hash(manifest) or info.get('windows_sha256') != manifest['windows_sha256']:
            raise ValueError('Pilot index does not match the current frozen corpus; rebuild that pilot engine.')
        config = embedding_config(engine)
        if any(info.get(key) != value for key, value in config.items()):
            raise ValueError('Embedding configuration changed; rebuild the pilot before querying.')
        _check_local_limit([query], 'query')
        cache = folder / 'queries' / canonical_hash(config)
        path = cache / (canonical_hash({'query': query, 'kind': 'query', 'config': config}) + '.npy')
        if path.exists():
            vector = _load_vectors(path, 1, config['dimensions'])[0]
        else:
            matrix = embed_local([query], kind='query') if engine == 'local' else embed_openai(lib.state, [query], scope=scope)
            matrix = _validate_vectors(matrix, 1, config['dimensions'])
            _save_vectors(path, matrix)
            vector = matrix[0]
        from usearch.index import Index

        index_path = (folder / info['index_file']).resolve()
        if folder.resolve() not in index_path.parents:
            raise ValueError('Pilot index path is outside its engine directory.')
        index = Index.restore(str(index_path), view=True)
        matches = index.search(vector, min(max(1, int(limit)), len(windows), 200))
        seen = set()
        results = []
        for match in matches:
            w = windows[int(match.key)]
            if w['passage_id'] in seen:
                continue
            try:
                lib.read(w['passage_id'], context=0)
            except ValueError:
                continue  # changed/removed passages cannot become current evidence
            seen.add(w['passage_id'])
            results.append({'passage_id': w['passage_id'], 'work_id': w['work_id'], 'distance': float(match.distance), 'window_id': w['id']})
        return results
