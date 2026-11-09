"""Controlled semantic pilot contracts, with fake models/API and real local indexes."""
from __future__ import annotations

import hashlib
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from book_library import semantic as sem
from book_library.budget import Budget, BudgetExceeded
from book_library.storage import atomic_json, read_json

REV = 'a' * 40


class FakeModel:
    def __init__(self):
        self.calls = []
        self.tokenizer = lambda text: {'input_ids': list(range(len(text.split()) + 2))}

    def encode(self, texts, **kwargs):
        self.calls.append(list(texts))
        result = np.zeros((len(texts), sem.LOCAL_DIMENSIONS), dtype=np.float32)
        for i, text in enumerate(texts):
            result[i, int(hashlib.sha256(text.encode()).hexdigest(), 16) % sem.LOCAL_DIMENSIONS] = 1
        return result


class FakeLibrary:
    def __init__(self, root):
        self.state = root / '.library'
        self.state.mkdir()
        self.files = {}
        self.missing_passages = set()
        for i in range(12):
            p = root / f'{i}.txt'
            p.write_text(f'original source {i}')
            stat = p.stat()
            self.files[f'f{i}'] = {'id': f'f{i}', 'work_id': f'w{i}', 'path': str(p), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest(), 'available': True, 'state': 'ready', 'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns}

    def _catalog(self):
        return {'files': self.files, 'works': {f'w{i}': {'id': f'w{i}'} for i in range(12)}}

    def read(self, pid, context=0):
        if pid in self.missing_passages:
            raise ValueError('Source disappeared')
        return {'passage': {'id': pid}}


@pytest.fixture
def pilot(tmp_path, monkeypatch):
    model = FakeModel()
    monkeypatch.setattr(sem, 'local_model', lambda: model)
    monkeypatch.setattr(sem, 'local_revision', lambda: REV)
    lib = FakeLibrary(tmp_path)
    windows = [{'id': f'v{i}', 'work_id': f'w{i}', 'passage_id': f'p{i}', 'section_id': f's{i}', 'text': f'Title {i}\nGrounded sample number {i}', 'token_count': 9, 'source_text_sha256': hashlib.sha256(f'text{i}'.encode()).hexdigest()} for i in range(12)]
    queries = [{'id': f'q{i}', 'query': f'question {i}', 'kind': 'direct', 'work_id': f'w{i % 12}', 'anchor': {'text_needle': f'number {i % 12}'}, 'expected_passage_ids': [f'p{i % 12}']} for i in range(24)]
    manifest = {'frozen': True, 'generation': 'test-generation', 'work_ids': [f'w{i}' for i in range(12)], 'query_count': 24, 'queries_sha256': sem.canonical_hash(queries), 'windows_sha256': sem.canonical_hash(windows), 'tokenizer_revision': REV, 'source_hashes': {fid: f['sha256'] for fid, f in lib.files.items()}}
    atomic_json(lib.state / 'pilot/windows.json', windows)
    atomic_json(lib.state / 'pilot/queries.json', queries)
    atomic_json(lib.state / 'pilot/manifest.json', manifest)
    return lib, windows, manifest, model


def test_only_frozen_exact_twelve_book_and_24_query_corpus_can_build(pilot):
    lib, windows, manifest, model = pilot
    with pytest.raises(ValueError, match='Unknown'):
        sem.build_engine(lib, '../other', windows)
    changed = [dict(w) for w in windows]
    changed[0]['text'] = 'silently replaced passage'
    with pytest.raises(ValueError, match='differ'):
        sem.build_engine(lib, 'local', changed)
    manifest['work_ids'].append('extra-book')
    atomic_json(lib.state / 'pilot/manifest.json', manifest)
    with pytest.raises(ValueError, match='twelve'):
        sem.build_engine(lib, 'local', windows)
    manifest['work_ids'].pop()
    manifest['query_count'] = 23
    atomic_json(lib.state / 'pilot/manifest.json', manifest)
    with pytest.raises(ValueError, match='24-query'):
        sem.build_engine(lib, 'local', windows)
    assert not model.calls


def test_local_limit_includes_prefix_special_tokens_and_never_truncates(pilot):
    *_, model = pilot
    assert sem.embed_local(['word ' * 509]).shape == (1, 384)  # 509 + prefix + two special tokens
    with pytest.raises(ValueError, match='512-token'):
        sem.embed_local(['word ' * 510])
    assert model.calls[0][0].startswith('passage: ')
    sem.embed_local(['small query'], kind='query')
    assert model.calls[-1] == ['query: small query']


def test_cached_batches_are_bound_to_manifest_model_and_window_content(pilot):
    lib, windows, manifest, model = pilot
    first = sem.build_engine(lib, 'local', windows)
    second = sem.build_engine(lib, 'local', windows)
    assert first['embedded_batches'] == 1 and first['cached_batches'] == 0
    assert second['embedded_batches'] == 0 and second['cached_batches'] == 1
    assert len(model.calls) == 1
    assert first['model_revision'] == REV
    windows[0]['text'] += ' revised'
    manifest['windows_sha256'] = sem.canonical_hash(windows)
    atomic_json(lib.state / 'pilot/windows.json', windows)
    atomic_json(lib.state / 'pilot/manifest.json', manifest)
    third = sem.build_engine(lib, 'local', windows)
    assert third['cache_fingerprint'] != first['cache_fingerprint']
    assert third['embedded_batches'] == 1
    assert len(model.calls) == 2


def test_invalid_cache_is_rejected_without_another_embedding_request(pilot):
    lib, windows, _, model = pilot
    info = sem.build_engine(lib, 'local', windows)
    folder = lib.state / 'pilot/local/builds' / info['cache_fingerprint']
    path = next(folder.glob('batch-*.npy'))
    with path.open('wb') as stream:
        np.save(stream, np.full((12, 384), np.nan))
    with pytest.raises(ValueError, match='cache is invalid'):
        sem.build_engine(lib, 'local', windows)
    assert len(model.calls) == 1


def test_vector_dimensions_and_finite_values_are_checked_before_publication(pilot, monkeypatch):
    lib, windows, _, _ = pilot
    monkeypatch.setattr(sem, 'embed_local', lambda texts: np.ones((len(texts), 383)))
    with pytest.raises(ValueError, match='shape mismatch'):
        sem.build_engine(lib, 'local', windows)
    assert not (lib.state / 'pilot/local/engine.json').exists()
    monkeypatch.setattr(sem, 'embed_local', lambda texts: np.full((len(texts), 384), np.inf))
    with pytest.raises(ValueError, match='finite'):
        sem.build_engine(lib, 'local', windows)


def test_query_cache_is_reused_and_configuration_changes_require_rebuild(pilot, monkeypatch):
    lib, windows, _, model = pilot
    sem.build_engine(lib, 'local', windows)
    first = sem.semantic_search(lib, 'river memory', 'local')
    assert first
    count = len(model.calls)
    assert sem.semantic_search(lib, 'river memory', 'local') == first
    assert len(model.calls) == count
    monkeypatch.setattr(sem, 'local_revision', lambda: 'b' * 40)
    with pytest.raises(ValueError, match='configuration changed'):
        sem.semantic_search(lib, 'river memory', 'local')
    assert len(model.calls) == count


def test_changed_frozen_source_cannot_be_embedded_and_deleted_hits_hidden(pilot):
    lib, windows, _, _ = pilot
    sem.build_engine(lib, 'local', windows)
    Path(lib.files['f0']['path']).write_text('changed bytes')
    with pytest.raises(ValueError, match='changed'):
        sem.build_engine(lib, 'local', windows)
    lib.missing_passages.add('p0')
    assert all(r['passage_id'] != 'p0' for r in sem.semantic_search(lib, 'river memory', 'local'))


def test_parallel_builds_and_queries_share_consistent_atomic_caches(pilot):
    lib, windows, _, model = pilot
    with ThreadPoolExecutor(max_workers=2) as pool:
        builds = list(pool.map(lambda _: sem.build_engine(lib, 'local', windows), range(2)))
    assert sum(r['embedded_batches'] for r in builds) == 1
    assert len(model.calls) == 1
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: sem.semantic_search(lib, 'same concurrent query', 'local'), range(2)))
    assert results[0] == results[1]
    assert len(model.calls) == 2


def fake_openai(monkeypatch, state, behavior='success', lifecycle=None):
    calls = []
    def factory(**options):
        assert options['max_retries'] == 0
        assert options['base_url'] == 'https://api.openai.com/v1'
        client_state = {'closed': False}
        if lifecycle is not None:
            lifecycle.append(client_state)
        def close():
            client_state['closed'] = True
            if behavior == 'close-error':
                raise RuntimeError('Private cleanup message must not appear')
        class Embeddings:
            def create(self, **request):
                calls.append({'options': options, 'request': request, 'ledger_requests': Budget(state).report()['requests']})
                if behavior == 'timeout':
                    raise TimeoutError('This fake provider error contains a secret that must not be echoed')
                if behavior == 'chained-error':
                    try:
                        raise OSError('Private socket message must not appear')
                    except OSError as cause:
                        raise ConnectionError('Private request message must not appear') from cause
                rows = []
                for i, _ in enumerate(request['input']):
                    vector = [0.] * 3072
                    vector[i] = float('nan') if behavior == 'nan' else 1.
                    rows.append(SimpleNamespace(index=i, embedding=vector))
                return SimpleNamespace(data=list(reversed(rows)), usage=SimpleNamespace(total_tokens=10))
        return SimpleNamespace(embeddings=Embeddings(), close=close)
    monkeypatch.setitem(sys.modules, 'openai', SimpleNamespace(OpenAI=factory))
    monkeypatch.setattr(sem, 'api_key', lambda _: 'fake-key-never-sent')
    return calls


def test_api_attempts_reserved_no_hidden_retries_usage_settled_before_vector_validation(pilot, monkeypatch):
    lib, *_ = pilot
    calls = fake_openai(monkeypatch, lib.state)
    result = sem.embed_openai(lib.state, ['small passage'])
    assert result.shape == (1, 3072)
    assert calls[0]['ledger_requests'] == 1
    assert calls[0]['request']['dimensions'] == 3072
    assert 'encoding_format' not in calls[0]['request']
    assert Budget(lib.state).report()['actual_tokens'] == 10
    calls = fake_openai(monkeypatch, lib.state, 'nan')
    with pytest.raises(ValueError, match='finite'):
        sem.embed_openai(lib.state, ['bad result'])
    assert Budget(lib.state).report()['actual_tokens'] == 20


def test_timeout_and_explicit_retry_both_remain_reserved_without_secret_output(pilot, monkeypatch):
    lib, *_ = pilot
    calls = fake_openai(monkeypatch, lib.state, 'timeout')
    for _ in range(2):
        with pytest.raises(RuntimeError, match='reservation is retained') as error:
            sem.embed_openai(lib.state, ['timed out request'])
        assert 'secret' not in str(error.value)
    assert len(calls) == 2
    assert Budget(lib.state).report()['uncertain_reservations'] == 2


@pytest.mark.parametrize('behavior,error', [('success', None), ('timeout', RuntimeError), ('nan', ValueError)])
def test_client_closed_after_success_request_error_or_invalid_response(pilot, monkeypatch, behavior, error):
    lib, *_ = pilot
    lifecycle = []
    fake_openai(monkeypatch, lib.state, behavior, lifecycle=lifecycle)
    if error:
        with pytest.raises(error):
            sem.embed_openai(lib.state, ['A disposable passage.'])
    else:
        sem.embed_openai(lib.state, ['A disposable passage.'])
    assert lifecycle == [{'closed': True}]


def test_client_closed_when_budget_rejects_before_request(pilot, monkeypatch):
    lib, *_ = pilot
    lifecycle = []
    calls = fake_openai(monkeypatch, lib.state, lifecycle=lifecycle)
    def exhausted(*args, **kwargs):
        raise BudgetExceeded('Test ceiling reached.')
    monkeypatch.setattr(Budget, 'reserve', exhausted)
    with pytest.raises(BudgetExceeded):
        sem.embed_openai(lib.state, ['A disposable passage.'])
    assert calls == [] and lifecycle == [{'closed': True}]


def test_transport_diagnostic_shows_only_exception_types(pilot, monkeypatch):
    lib, *_ = pilot
    lifecycle = []
    fake_openai(monkeypatch, lib.state, 'chained-error', lifecycle=lifecycle)
    with pytest.raises(RuntimeError, match='ConnectionError -> OSError') as error:
        sem.embed_openai(lib.state, ['Source text must not appear'])
    assert 'Private' not in str(error.value) and 'Source text' not in str(error.value)
    assert lifecycle == [{'closed': True}]
    assert Budget(lib.state).report()['uncertain_reservations'] == 1


def test_cleanup_failure_does_not_discard_success_or_leak_message(pilot, monkeypatch, caplog):
    lib, *_ = pilot
    fake_openai(monkeypatch, lib.state, 'close-error')
    result = sem.embed_openai(lib.state, ['A disposable passage.'])
    assert result.shape == (1, 3072)
    assert 'cleanup failed (RuntimeError)' in caplog.text
    assert 'Private' not in caplog.text


def test_real_sdk_uses_compact_wire_format_and_decodes_before_validation(pilot, monkeypatch):
    import base64
    import httpx
    import openai

    lib, *_ = pilot
    real_factory = openai.OpenAI
    clients = []
    observed = []
    def transport(request):
        body = json.loads(request.content)
        observed.append(body)
        assert body['encoding_format'] == 'base64'
        assert Budget(lib.state).report()['requests'] == 1
        vectors = np.zeros((2, 3072), dtype=np.float32)
        vectors[0, 5] = 2.
        vectors[1, 10] = 4.
        return httpx.Response(200, json={
            'object': 'list', 'model': sem.OPENAI_MODEL,
            'data': [{'object': 'embedding', 'index': i,
                      'embedding': base64.b64encode(vectors[i].tobytes()).decode('ascii')}
                     for i in (1, 0)],
            'usage': {'prompt_tokens': 17, 'total_tokens': 17},
        })
    def factory(**options):
        http = httpx.Client(transport=httpx.MockTransport(transport))
        clients.append(http)
        return real_factory(**options, http_client=http)
    monkeypatch.setattr(openai, 'OpenAI', factory)
    monkeypatch.setattr(sem, 'api_key', lambda _: 'fake-key-never-sent')
    result = sem.embed_openai(lib.state, ['First disposable passage.', 'Second disposable passage.'])
    assert len(observed) == 1 and observed[0]['dimensions'] == 3072
    assert result.shape == (2, 3072) and result.dtype == np.float32
    assert result[0, 5] == result[1, 10] == 1.
    assert np.count_nonzero(result) == 2
    assert clients[0].is_closed
    assert Budget(lib.state).report()['actual_tokens'] == 17


def test_pilot_evaluation_query_charged_pilot_and_ordinary_query_monthly(pilot, monkeypatch):
    lib, windows, _, _ = pilot
    fake_openai(monkeypatch, lib.state)
    info = sem.build_engine(lib, 'openai', windows)
    assert info['api_usage']['requests'] == 1
    assert info['api_usage']['actual_tokens'] == 10
    sem.semantic_search(lib, 'frozen evaluation question', 'openai', scope='pilot')
    assert Budget(lib.state).report()['spent_or_reserved']['monthly'] == 0
    atomic_json(lib.state / 'config.json', {**read_json(lib.state / 'config.json', {}), 'semantic': {'enabled': True, 'full_build_approved': True, 'engine': 'openai'}})
    sem.semantic_search(lib, 'ordinary research question', 'openai')
    assert Budget(lib.state).report()['spent_or_reserved']['monthly'] > 0
    before = Budget(lib.state).report()['requests']
    atomic_json(lib.state / 'config.json', {**read_json(lib.state / 'config.json', {}), 'semantic': {'enabled': True, 'full_build_approved': True, 'engine': 'openai'}})
    sem.semantic_search(lib, 'ordinary research question', 'openai')
    assert Budget(lib.state).report()['requests'] == before


def test_env_reference_parser_handles_quotes_and_comments_without_copying_key(tmp_path, monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.delenv('LIBRARY_OPENAI_ENV', raising=False)
    env = tmp_path / 'existing.env'
    env.write_text('  export OPENAI_API_KEY="fictional-value" # comment\n')
    state = tmp_path / 'private-state'
    atomic_json(state / 'config.json', {'openai_env_file': str(env)})
    assert sem.api_key(state) == 'fictional-value'
    assert 'fictional-value' not in (state / 'config.json').read_text()
    env.write_text('OPENAI_API_KEY="unterminated value\n')
    with pytest.raises(ValueError, match='malformed') as error:
        sem.api_key(state)
    assert 'unterminated value' not in str(error.value)


def test_interrupted_api_build_resumes_completed_batches_without_repaying(pilot, monkeypatch):
    lib, windows, manifest, _ = pilot
    expanded = []
    for i in range(72):
        original = windows[i % 12]
        expanded.append({**original, 'id': f'large-window-{i}', 'text': f'Window {i} from source {i % 12}'})
    manifest['windows_sha256'] = sem.canonical_hash(expanded)
    atomic_json(lib.state / 'pilot/windows.json', expanded)
    atomic_json(lib.state / 'pilot/manifest.json', manifest)
    calls = []
    def embedding(state, texts, scope='pilot'):
        calls.append(len(texts))
        if len(calls) == 2:
            raise TimeoutError('Simulated second-batch failure')
        return np.ones((len(texts), 3072), dtype=np.float32)
    monkeypatch.setattr(sem, 'embed_openai', embedding)
    with pytest.raises(TimeoutError):
        sem.build_engine(lib, 'openai', expanded)
    assert not (lib.state / 'pilot/openai/engine.json').exists()
    result = sem.build_engine(lib, 'openai', expanded)
    assert calls == [64, 8, 8]
    assert result['cached_batches'] == 1
    assert result['embedded_batches'] == 1
