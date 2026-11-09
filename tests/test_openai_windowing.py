"""Real lightweight tokenizer and real builder; only the external API is fake."""
from __future__ import annotations

import builtins
import pytest

from book_library import intake, openai_windowing, public_config, semantic_library as sem
from book_library.service import Library
from book_library.storage import atomic_json, read_json
from test_service import docx
from test_semantic import fake_openai


def drain(lib):
    for _ in range(40):
        if not intake.run_next(lib):
            return
    pytest.fail('Synthetic intake did not finish.')


def enable(lib):
    public_config.accept_budget(lib, initial_usd='10', monthly_usd='10', timezone='UTC')
    sem.configure_engine(lib, 'openai', approval_evidence='Synthetic fixture authorizes OpenAI indexing.')


def sent(calls):
    return '\n'.join(text for call in calls for text in call['request']['input'])


def test_unicode_windows_preserve_source_codepoints_and_have_no_gaps(tmp_path):
    encoding = openai_windowing.encoding()
    text = ('👩🏽‍💻 Café e\u0301 漢字 한국어 Ελληνικά العربية 𝄞 🧙🏻‍♂️\n'
            'Literal source marker <|endoftext|> remains data.\n') * 140
    with sem._cache(tmp_path, openai_windowing.config()) as cache:
        parts = openai_windowing.segments(cache, encoding, '書籍👩🏽‍💻' * 140, 'A heading', text)
    assert len(parts) > 2
    covered = 0
    for part in parts:
        a, b = part['char_start'], part['char_end']
        assert 0 <= a < b <= len(text)
        assert a <= covered
        assert part['text'].endswith(text[a:b])
        assert '\ufffd' not in part['text']
        assert len(openai_windowing.encode(encoding, part['text'])) == part['token_count'] <= 512
        covered = max(covered, b)
    assert covered == len(text)


def test_fresh_estimate_build_and_query_never_import_model_stack(tmp_path, monkeypatch):
    root = tmp_path / 'books'
    docx(root / 'Native' / 'source.docx', [('Heading1', 'A real tokenizer'), 'Unicode café 🧙🏻‍♂️ 漢字 and exact source offsets.'])
    lib = Library(root)
    lib.sync(semantic=False)
    calls = fake_openai(monkeypatch, lib.state)
    real_import = builtins.__import__
    def guarded(name, *args, **kwargs):
        if name.split('.')[0] in {'torch', 'transformers', 'sentence_transformers'}:
            pytest.fail('Fresh OpenAI flow imported heavyweight model code: ' + name)
        return real_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', guarded)
    settings_before = (lib.state / 'config.json').read_bytes()
    estimate = sem.estimate_index(lib, engine='openai')
    assert estimate['uncached_tokens'] > 0 and not calls
    assert (lib.state / 'config.json').read_bytes() == settings_before
    enable(lib)
    info = sem.build_index(lib)
    assert info['config'] == openai_windowing.config()
    assert info['embedded_windows'] > 0 and calls
    before = len(calls)
    assert sem.build_index(lib)['changed'] is False
    assert len(calls) == before
    assert sem.search(lib, 'café')
    assert len(calls) == before + 1
    assert sem.search(lib, 'café')
    assert len(calls) == before + 1


def test_intake_scope_does_not_upload_an_earlier_local_only_book(tmp_path, monkeypatch):
    root = tmp_path / 'books'
    first = docx(root / 'Private' / 'source.docx', [('Heading1', 'Private'), 'LOCAL_ONLY_SENTINEL must remain outside another intake.'])
    lib = Library(root)
    enable(lib)
    calls = fake_openai(monkeypatch, lib.state)
    local = lib.intake(first.parent, local_only=True)
    drain(lib)
    assert not calls
    second = docx(root / 'Approved' / 'source.docx', [('Heading1', 'Approved'), 'APPROVED_SENTINEL may be embedded by this intake.'])
    approved = lib.intake(second.parent)
    drain(lib)
    assert lib.intake_status(approved['id'])['readiness']['semantic'] == 'ready'
    assert 'APPROVED_SENTINEL' in sent(calls)
    assert 'LOCAL_ONLY_SENTINEL' not in sent(calls)
    active = read_json(lib.state / 'semantic/current.json')
    status = sem.status(lib)
    assert active['exact_generation'] == lib._active()['generation']
    assert status['pending'] and status['excluded_source_files'] == 1
    assert status['scope'] == 'authorized intake sources'
    assert status['coverage_books'] == 1 and status['total_books'] == 2
    assert lib.intake_status(local['id'])['readiness']['semantic'] == 'not_requested'
    assert not read_json(lib.state / 'config.json')['semantic'].get('openai_initial_complete')
    first_snapshot = active['snapshot_id']
    # An explicit whole-library build is a distinct authorization and scope.
    complete = sem.build_index(lib)
    assert complete['snapshot_id'] != first_snapshot
    assert complete['budget_scope'] == 'initial'
    assert 'LOCAL_ONLY_SENTINEL' in sent(calls)
    assert not sem.status(lib)['pending']
    assert read_json(lib.state / 'config.json')['semantic']['openai_initial_complete']
    assert complete['initial_build_completed']
    # Subsequent monthly intake publication must preserve the initial flag.
    third = docx(root / 'Third' / 'source.docx', ['A later approved book.'])
    lib.intake(third.parent)
    drain(lib)
    assert read_json(lib.state / 'config.json')['semantic']['openai_initial_complete']
    assert read_json(lib.state / 'semantic/current.json')['initial_build_completed']


def test_local_revision_of_a_published_book_does_not_inherit_upload_permission(tmp_path, monkeypatch):
    root = tmp_path / 'books'
    first = docx(root / 'Changed' / 'source.docx', [('Heading1', 'First version'), 'PUBLISHED_OLD_SENTINEL is approved.'])
    lib = Library(root)
    enable(lib)
    calls = fake_openai(monkeypatch, lib.state)
    lib.intake(first.parent)
    drain(lib)
    assert 'PUBLISHED_OLD_SENTINEL' in sent(calls)
    calls.clear()
    docx(first, [('Heading1', 'New local version'), 'NEW_LOCAL_VERSION_SENTINEL is not approved for this later intake.'])
    lib.intake(first.parent, local_only=True)
    drain(lib)
    assert not calls
    second = docx(root / 'Other' / 'source.docx', ['A separately approved new source.'])
    lib.intake(second.parent)
    drain(lib)
    assert calls
    assert 'NEW_LOCAL_VERSION_SENTINEL' not in sent(calls)
    assert sem.status(lib)['pending']


def test_local_model_permission_is_not_openai_permission(tmp_path, monkeypatch):
    root = tmp_path / 'books'
    first = docx(root / 'Local' / 'source.docx', ['LOCAL_MODEL_SENTINEL was indexed only by a local model.'])
    lib = Library(root)
    lib.sync(semantic=False)
    local_files = {fid: {'sha256': record['sha256']} for fid, record in lib._catalog()['files'].items()}
    # A legacy local-model generation grants no permission to send these bytes.
    atomic_json(lib.state / 'semantic/current.json', {'engine': 'local', 'files': local_files, 'authorized_files': local_files})
    enable(lib)
    calls = fake_openai(monkeypatch, lib.state)
    second = docx(root / 'Cloud' / 'source.docx', ['Explicitly authorized OpenAI source.'])
    lib.intake(second.parent)
    drain(lib)
    assert calls and 'LOCAL_MODEL_SENTINEL' not in sent(calls)


def test_intake_job_hash_survives_a_source_change_before_scope_merge(tmp_path, monkeypatch):
    root = tmp_path / 'books'
    source = docx(root / 'Approved' / 'source.docx', ['The initially approved version.'])
    lib = Library(root)
    enable(lib)
    calls = fake_openai(monkeypatch, lib.state)
    job = lib.intake(source.parent)
    intake._index(lib, job['id'])
    approved_hash = job['files'][0]['sha256']
    merge = sem._merge_intake_scope
    seen = []

    def edit_before_merge(lib, file_ids, current, engine, source_bindings=None):
        seen.append(source_bindings)
        assert {item['sha256'] for item in source_bindings.values()} == {approved_hash}
        docx(source, ['UNAPPROVED_REPLACEMENT_SENTINEL arrived after intake authorization.'])
        lib.sync(source.parent, semantic=False)
        return merge(lib, file_ids, current, engine, source_bindings)

    monkeypatch.setattr(sem, '_merge_intake_scope', edit_before_merge)
    intake._semantic(lib, job['id'])
    assert seen and not calls
    assert not (lib.state / 'costs.jsonl').exists()
    assert lib.intake_status(job['id'])['readiness']['semantic'] == 'pending'


def test_published_source_hash_survives_a_source_change_before_snapshot(tmp_path, monkeypatch):
    root = tmp_path / 'books'
    first = docx(root / 'Earlier' / 'source.docx', ['The previously published approved version.'])
    lib = Library(root)
    enable(lib)
    calls = fake_openai(monkeypatch, lib.state)
    lib.intake(first.parent)
    drain(lib)
    current = read_json(lib.state / 'semantic/current.json')
    original_bindings = current['authorized_files']
    second = docx(root / 'Next' / 'source.docx', ['The separately approved next intake.'])
    job = lib.intake(second.parent)
    intake._index(lib, job['id'])
    calls.clear()
    costs_before = (lib.state / 'costs.jsonl').read_bytes()
    snapshot = sem._snapshot
    seen = []

    def edit_before_snapshot(lib, config, cache, **scope):
        seen.append(scope)
        for fid, binding in original_bindings.items():
            assert scope['source_bindings'][fid] == binding
        docx(first, ['UNAPPROVED_OLD_BOOK_REVISION_SENTINEL arrived after scope selection.'])
        lib.sync(first.parent, semantic=False)
        return snapshot(lib, config, cache, **scope)

    monkeypatch.setattr(sem, '_snapshot', edit_before_snapshot)
    intake._semantic(lib, job['id'])
    assert seen and not calls
    assert (lib.state / 'costs.jsonl').read_bytes() == costs_before
    assert read_json(lib.state / 'semantic/current.json')['generation'] == current['generation']
    assert lib.intake_status(job['id'])['readiness']['semantic'] == 'pending'


@pytest.mark.parametrize('first_mutation', ['taxonomy', 'focus', 'catalog'])
def test_ordinary_library_records_are_never_paid_authorization(tmp_path, monkeypatch, first_mutation):
    from book_library.taxonomy import save_term
    from book_library import review_ai
    lib = Library(tmp_path / 'books')
    if first_mutation == 'taxonomy':
        save_term(lib, 'synthetic-topic', {'label': 'Synthetic topic', 'evidence': 'Fixture editorial choice'})
    elif first_mutation == 'focus':
        lib.save_focus('synthetic-focus', {'name': 'Synthetic focus', 'subjects': []})
    else:
        atomic_json(lib.state / 'catalog.json', {'works': {}, 'files': {}, 'acquisitions': {}})
    status = public_config.settings_status(lib)
    assert not status['budget_accepted']
    assert status['budget']['initial_usd'] == status['budget']['monthly_usd'] == '10'
    monkeypatch.setenv('OPENAI_API_KEY', 'unapproved-synthetic-key')
    with pytest.raises(ValueError, match='Accept spending'):
        public_config.set_review_default(lib, True)
    with pytest.raises(ValueError, match='Accept spending'):
        sem.configure_engine(lib, 'openai', approval_evidence='Feature choice without budget acceptance')
    assert not (lib.state / 'costs.jsonl').exists()


def test_missing_window_configuration_never_silently_reembeds_paid_vectors(tmp_path, monkeypatch):
    root = tmp_path / 'books'
    docx(root / 'Book' / 'source.docx', ['A source with saved paid embedding vectors.'])
    lib = Library(root)
    lib.sync(semantic=False)
    enable(lib)
    calls = fake_openai(monkeypatch, lib.state)
    sem.build_index(lib)
    before = len(calls)
    (lib.state / 'semantic/current.json').unlink()
    (lib.state / 'semantic/windowing-openai.json').unlink()
    for path in (lib.state / 'semantic/snapshots').glob('*.json'):
        path.unlink()
    with pytest.raises(ValueError, match='window configuration is missing'):
        sem.build_index(lib)
    assert len(calls) == before


@pytest.mark.parametrize('record', ['marker', 'published'])
def test_empty_window_configuration_is_not_replaced_implicitly(tmp_path, record):
    root = tmp_path / 'books'
    docx(root / 'Book' / 'source.docx', ['Source text for an invalid configuration check.'])
    lib = Library(root)
    lib.sync(semantic=False)
    if record == 'marker':
        atomic_json(lib.state / 'semantic/windowing-openai.json', {})
    else:
        atomic_json(lib.state / 'semantic/current.json', {'engine': 'openai', 'config': {}})
    with pytest.raises(ValueError, match='configuration'):
        sem.estimate_index(lib, engine='openai')
    assert not (lib.state / 'costs.jsonl').exists()
