"""Public setup never derives paid permission from credentials or later defaults."""
import pytest

from book_library import intake, public_config, semantic_library
from book_library.budget import Budget, BudgetExceeded
from book_library.service import Library
from book_library.storage import atomic_json, read_json
from test_service import docx


def fresh(tmp_path):
    root = tmp_path / 'books'
    source = docx(root / 'First' / 'source.docx', [('Heading1', 'A chapter'), 'Copper birds sing beside the patient river.'])
    return Library(root), source


def drain(lib):
    for _ in range(50):
        if not intake.run_next(lib):
            return
    pytest.fail('Fixture intake did not settle.')


def providers(monkeypatch):
    calls = {'semantic': [], 'review': []}
    def build(lib, **kwargs):
        calls['semantic'].append(kwargs)
        return {}
    def review(lib, context, **kwargs):
        calls['review'].append(context['target']['id'])
        return {'status': 'complete', 'suggestions': [], 'unresolved': [], 'assessments': [], 'warnings': [], 'model': 'fixture', 'cost': None}
    monkeypatch.setattr(semantic_library, 'build_index', build)
    monkeypatch.setattr('book_library.review_ai.suggest', review)
    return calls


def accept(lib):
    public_config.accept_budget(lib, timezone='UTC', approval_evidence='Synthetic test explicitly accepts $10/$10.')


@pytest.mark.parametrize('key', [None, 'not-a-real-key'])
def test_fresh_intake_with_key_does_not_authorize_or_reserve(tmp_path, monkeypatch, key):
    if key is None:
        monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    else:
        monkeypatch.setenv('OPENAI_API_KEY', key)
    lib, source = fresh(tmp_path)
    calls = providers(monkeypatch)
    job = lib.intake(source.parent)
    drain(lib)
    done = lib.intake_status(job['id'])
    assert done['status'] == 'complete'
    assert done['readiness'] == {'text': 'ready', 'semantic': 'not_requested', 'metadata_review': 'not_requested'}
    assert done['counts']['reviewed'] == 0
    assert all(target['status'] == 'not_requested' for target in done['targets'])
    assert calls == {'semantic': [], 'review': []}
    assert not (lib.state / 'costs.jsonl').exists()
    assert not public_config.settings_status(lib)['budget_accepted']
    assert lib.search('copper birds', engine='exact')['direct']


@pytest.mark.parametrize('semantic,review', [(True, False), (False, True), (True, True)])
def test_capabilities_are_independent(tmp_path, monkeypatch, semantic, review):
    lib, source = fresh(tmp_path)
    calls = providers(monkeypatch)
    accept(lib)
    if semantic:
        semantic_library.configure_engine(lib, 'openai', approval_evidence='Test approval')
    if review:
        public_config.set_review_default(lib, True)
    job = lib.intake(source.parent)
    drain(lib)
    assert bool(calls['semantic']) is semantic
    assert bool(calls['review']) is review
    assert lib.intake_status(job['id'])['status'] == 'complete'
    if semantic:
        assert calls['semantic'][0]['budget_scope'] == 'monthly'


def test_intake_permission_snapshots_and_overrides(tmp_path, monkeypatch):
    lib, first = fresh(tmp_path)
    calls = providers(monkeypatch)
    old = lib.intake(first.parent)
    accept(lib)
    semantic_library.configure_engine(lib, 'openai', approval_evidence='Test approval')
    public_config.set_review_default(lib, True)
    second = docx(lib.root / 'Second' / 'second.docx', ['The second book tells a new story.'])
    inherited = lib.intake(second.parent)
    third = docx(lib.root / 'Third' / 'third.docx', ['The third book stays wholly local in this intake.'])
    local = lib.intake(third.parent, local_only=True)
    fourth = docx(lib.root / 'Fourth' / 'fourth.docx', ['This book requests no automatic metadata review.'])
    overridden = lib.intake(fourth.parent, review_metadata=False)
    public_config.set_review_default(lib, False)
    drain(lib)
    assert not lib.intake_status(old['id'])['authorization']['semantic']
    assert lib.intake_status(old['id'])['readiness']['metadata_review'] == 'not_requested'
    assert lib.intake_status(inherited['id'])['readiness']['metadata_review'] == 'complete'
    assert lib.intake_status(local['id'])['readiness']['semantic'] == 'not_requested'
    assert lib.intake_status(local['id'])['readiness']['metadata_review'] == 'not_requested'
    assert lib.intake_status(overridden['id'])['readiness']['semantic'] == 'ready'
    assert lib.intake_status(overridden['id'])['readiness']['metadata_review'] == 'not_requested'
    assert len(calls['semantic']) == 2
    assert calls['review']


def test_later_review_preserves_identity_results_and_is_idempotent(tmp_path, monkeypatch):
    lib, source = fresh(tmp_path)
    calls = providers(monkeypatch)
    job = lib.intake(source.parent)
    drain(lib)
    before = lib.intake_status(job['id'])
    accept(lib)
    with pytest.raises(ValueError, match='Reload'):
        lib.review_intake(job['id'], expected_version=before['version'] - 1)
    requested = lib.review_intake(job['id'], expected_version=before['version'])
    assert requested['id'] == job['id'] and requested['authorization']['review_source'] == 'explicit_later_request'
    drain(lib)
    count = len(calls['review'])
    complete = lib.intake_status(job['id'])
    repeated = lib.review_intake(job['id'], expected_version=complete['version'])
    assert repeated['version'] == complete['version']
    drain(lib)
    assert len(calls['review']) == count and count > 0
    assert len(lib.intake_status()['intakes']) == 1
    assert calls['semantic'] == []


def test_later_review_rejects_changed_source(tmp_path):
    lib, source = fresh(tmp_path)
    job = lib.intake(source.parent)
    drain(lib)
    accept(lib)
    docx(source, ['Replacement content.'])
    with pytest.raises(ValueError, match='source files changed'):
        lib.review_intake(job['id'])
    # Explicit resume can refresh a completed local-only job before later review.
    lib.resume_intake(job['id'])
    drain(lib)
    assert lib.intake_status(job['id'])['readiness']['metadata_review'] == 'not_requested'
    requested = lib.review_intake(job['id'])
    assert requested['authorization']['review'] == 'every_indexed_heading'


def test_explicit_paid_requests_need_budget_acceptance(tmp_path):
    lib, source = fresh(tmp_path)
    public_config.initialize(lib)
    with pytest.raises(ValueError, match='Accept spending'):
        semantic_library.configure_engine(lib, 'openai', approval_evidence='Choose embeddings')
    with pytest.raises(ValueError, match='Accept spending'):
        lib.intake(source.parent, review_metadata=True)
    with pytest.raises(ValueError, match='Accept spending'):
        public_config.set_review_default(lib, True)
    with pytest.raises(ValueError, match='Accept spending'):
        Budget(lib.state).reserve_review()
    assert not (lib.state / 'costs.jsonl').exists()
    with pytest.raises(ValueError, match='by itself'):
        lib.intake(source.parent, local_only=True, review_metadata=False)


def test_estimate_before_authorization_never_changes_permission(tmp_path, monkeypatch):
    lib, _ = fresh(tmp_path)
    lib.sync(semantic=False)
    before = (lib.state / 'config.json').read_bytes()
    monkeypatch.setattr('book_library.semantic.embed_openai', lambda *a, **k: pytest.fail('Estimate called a provider'))
    estimate = semantic_library.estimate_index(lib, engine='openai')
    assert estimate['uncached_tokens'] > 0 and estimate['estimated_api_dollars'] > 0
    assert estimate['authorization_changed'] is False and estimate['local_cache_writes']
    assert (lib.state / 'config.json').read_bytes() == before
    assert not (lib.state / 'costs.jsonl').exists()


def test_budget_configuration_uses_limits_timezone_and_keeps_ledger(tmp_path):
    lib, _ = fresh(tmp_path)
    public_config.accept_budget(lib, initial_usd='2', monthly_usd='1', timezone='Pacific/Auckland')
    budget = Budget(lib.state)
    reservation = budget.reserve(1_000_000, 'monthly')
    before = (lib.state / 'costs.jsonl').read_bytes()
    public_config.accept_budget(lib, monthly_usd='0.13', timezone='Pacific/Auckland')
    assert (lib.state / 'costs.jsonl').read_bytes() == before
    assert budget.report()['monthly_timezone'] == 'Pacific/Auckland'
    assert budget.report()['ceilings']['initial'] == 2
    with pytest.raises(BudgetExceeded):
        budget.reserve(1, 'monthly')
    budget.settle(reservation, 1_000_000)
    for invalid in ['-1', 'NaN', 'Infinity', '1.001', True]:
        with pytest.raises(ValueError):
            public_config.accept_budget(lib, monthly_usd=invalid)
    with pytest.raises(ValueError, match='IANA'):
        public_config.accept_budget(lib, timezone='Not/AZone')


def test_legacy_migration_preserves_approvals_caps_and_saved_data(tmp_path):
    lib, _ = fresh(tmp_path)
    original = {'semantic': {'enabled': True, 'engine': 'openai', 'full_build_approved': True,
                            'openai_initial_complete': True, 'approval_evidence': 'Owner reviewed the pilot', 'approved_at': '2026-10-30'},
                'openai_env_file': '/private/key-reference', 'local_base_url': 'http://127.0.0.1:18765'}
    atomic_json(lib.state / 'config.json', original)
    atomic_json(lib.state / 'catalog.json', {'works': {}, 'files': {}})
    (lib.state / 'curation.jsonl').write_text('{"preserved":"history"}\n')
    before = (lib.state / 'curation.jsonl').read_bytes()
    result = public_config.migrate_legacy(lib, approval_evidence='Owner explicitly preserves existing behavior')
    config = read_json(lib.state / 'config.json')
    assert config['semantic'] == original['semantic']
    assert config['openai_env_file'] == original['openai_env_file']
    assert result['budget']['initial_usd'] == '50' and result['budget']['monthly_usd'] == '25'
    assert result['budget']['timezone'] == 'America/Chicago' and result['automatic_metadata_review']
    assert (lib.state / 'curation.jsonl').read_bytes() == before
    semantic_library.disable_engine(lib)
    semantic_library.configure_engine(lib, 'openai', approval_evidence='Re-enable explicitly')
    assert read_json(lib.state / 'config.json')['semantic']['openai_initial_complete']


def test_deleted_focus_is_not_resurrected(tmp_path):
    lib, _ = fresh(tmp_path)
    lib.sync(semantic=False)
    focuses = list((lib.state / 'focuses').glob('*.json'))
    assert focuses
    removed = focuses[0]
    removed.unlink()
    lib.sync(semantic=False)
    assert not removed.exists()


def test_uninitialized_status_is_unapproved_and_read_only(tmp_path):
    lib = Library(tmp_path / 'not-created')
    settings = public_config.settings_status(lib)
    assert not settings['budget_accepted']
    assert settings['budget']['initial_usd'] == '10'
    assert not lib.root.exists()


def test_legacy_queued_job_does_not_lose_its_authorization(tmp_path, monkeypatch):
    lib, source = fresh(tmp_path)
    calls = providers(monkeypatch)
    accept(lib)
    old = lib.intake(source.parent, review_metadata=True)
    saved = read_json(intake._path(lib, old['id']))
    for key in ('semantic', 'local_only', 'review_source'):
        saved['authorization'].pop(key, None)
    atomic_json(intake._path(lib, old['id']), saved)
    (lib.state / 'config.json').unlink()  # Legacy jobs existed before public setup.
    public_config.initialize(lib)
    assert public_config.settings_status(lib)['budget']['legacy']
    assert not public_config.settings_status(lib)['automatic_metadata_review']
    drain(lib)
    assert calls['review'] and not calls['semantic']
    assert lib.intake_status(old['id'])['status'] == 'complete'


def test_semantic_disable_is_enforced_before_next_provider_request(tmp_path, monkeypatch):
    from book_library import semantic as provider
    lib, _ = fresh(tmp_path)
    accept(lib)
    semantic_library.configure_engine(lib, 'openai', approval_evidence='Explicit test approval')
    semantic_library.disable_engine(lib)
    monkeypatch.setattr(provider, 'api_key', lambda *_: pytest.fail('Disabled provider requested credentials'))
    with pytest.raises(ValueError, match='authorization'):
        provider.embed_openai(lib.state, ['A query'], scope='monthly')
    assert semantic_library.status(lib)['state'] == 'disabled'
    assert not (lib.state / 'costs.jsonl').exists()


def test_paused_paid_queue_does_not_block_or_mislabel_local_only_intake(tmp_path, monkeypatch):
    lib, first = fresh(tmp_path)
    calls = providers(monkeypatch)
    accept(lib)
    paid = lib.intake(first.parent, review_metadata=True)
    saved = read_json(intake._path(lib, paid['id']))
    saved.update(status='paused', reason_code='budget', reason='Fixture allowance pause')
    atomic_json(intake._path(lib, paid['id']), saved)
    second = docx(lib.root / 'Local' / 'source.docx', ['This book can still be read locally.'])
    local = lib.intake(second.parent, local_only=True)
    assert 'paid_blocked_by' not in lib.intake_status(local['id'])
    drain(lib)
    assert lib.intake_status(local['id'])['status'] == 'complete'
    assert calls == {'semantic': [], 'review': []}


@pytest.mark.parametrize('key', [None, 'unapproved-test-key'])
def test_manual_review_explains_unaccepted_budget_without_opening_client(tmp_path, monkeypatch, key):
    from book_library import review_ai
    lib, _ = fresh(tmp_path)
    lib.sync(semantic=False)
    hit = lib.search('copper birds', engine='exact')['direct'][0]
    if key is None:
        monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    else:
        monkeypatch.setenv('OPENAI_API_KEY', key)
    monkeypatch.setattr(review_ai, 'api_key', lambda *_: pytest.fail('Unapproved review requested credentials'))
    monkeypatch.setattr(review_ai, '_make_client', lambda *_: pytest.fail('Unapproved review opened a client'))
    result = review_ai.suggest(lib, lib.review_context(hit['section_id']))
    assert result['failure_reason'] == 'budget'
    assert any('Accept spending limits' in warning for warning in result['warnings'])
    assert not (lib.state / 'costs.jsonl').exists()


def test_disabling_during_semantic_preparation_stops_request_before_reserving(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace
    from book_library import semantic as provider
    lib, _ = fresh(tmp_path)
    accept(lib)
    semantic_library.configure_engine(lib, 'openai', approval_evidence='Explicit fixture consent')
    closed = []
    def client(**kwargs):
        semantic_library.disable_engine(lib)
        return SimpleNamespace(embeddings=SimpleNamespace(create=lambda **kw: pytest.fail('Disabled request reached provider')),
                               close=lambda: closed.append(True))
    monkeypatch.setitem(sys.modules, 'openai', SimpleNamespace(OpenAI=client))
    monkeypatch.setattr(provider, 'api_key', lambda state: 'synthetic-key-never-sent')
    with pytest.raises(ValueError, match='authorization'):
        provider.embed_openai(lib.state, ['Query prepared before disable'], scope='monthly')
    assert closed == [True]
    assert not (lib.state / 'costs.jsonl').exists()
