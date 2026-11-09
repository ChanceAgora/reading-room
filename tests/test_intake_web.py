"""Intake JSON views retain readiness, provenance, actions, and conflict semantics."""
from copy import deepcopy

from fastapi.testclient import TestClient
import pytest

from book_library.intake import enqueue_intake, intake_status, _load, _save
from book_library.intake_curation import apply_automatic
from book_library.storage import writer
from book_library.web import create_app
from test_service import docx, seed

ORIGIN = 'http://127.0.0.1:8765'


@pytest.fixture
def intake_source(tmp_path):
    root = tmp_path / 'books'
    source = docx(root / 'Fixture' / 'Source.docx', [
        ('Heading1', 'Publication'), 'A Book of Introductions',
        'Published by Example Press. Publication year: 2024.',
        ('Heading1', 'Introduction'), 'Copper birds explain how this book is arranged.',
    ])
    lib = seed(root, [{'title': 'A Book of Introductions', 'paths': [source]}])
    hit = lib.search('copper birds', engine='exact')['direct'][0]
    from book_library.public_config import accept_budget
    accept_budget(lib, approval_evidence='Synthetic fixture explicitly requests metadata review.')
    job = enqueue_intake(lib, source.parent, review_metadata=True)
    with writer(lib.state):
        job = _load(lib, job['id'])
        job.update(status='running', stage='reviewing', work_ids=[hit['work_id']],
                   work_titles=['A Book of Introductions'], readiness={'text': 'ready', 'semantic': 'pending'},
                   targets=[{'id': hit['work_id'], 'work_id': hit['work_id'], 'scope': 'work',
                             'title': 'A Book of Introductions', 'status': 'no_change',
                             'review_url': '/review/' + hit['work_id'], 'coverage': {'complete': False, 'target_blocks_total': 8, 'target_blocks_supplied': 4}},
                            {'id': hit['section_id'], 'work_id': hit['work_id'], 'scope': 'section',
                             'title': 'Introduction', 'status': 'needs_evidence',
                             'review_url': '/review/' + hit['section_id'], 'coverage': {'complete': True, 'target_blocks_total': 2, 'target_blocks_supplied': 2}}])
        _save(lib, job)
    return lib, hit, job['id']


@pytest.fixture
def client(intake_source):
    with TestClient(create_app(intake_source[0]), base_url=ORIGIN) as client:
        yield client


def automatic_title(intake_source):
    lib, hit, identity = intake_source
    context = lib.review_context(hit['section_id'])
    heading = next(source for source in context['evidence'] if source['in_target'] and source['kind'] == 'heading')
    result = {'model': 'fixture', 'suggestions': [{
        'id': 'fixture-proposal', 'field': 'bibliography.title', 'value': heading['text'],
        'rationale': 'Use the actual heading as this contribution’s citation title.',
        'strength': 'well_supported', 'scope_supported': True, 'relationship': 'source_heading',
        'evidence': [{'source_id': heading['id'], 'quote': heading['text']}],
    }], 'unresolved': []}
    receipt = apply_automatic(lib, hit['section_id'], result, intake_id=identity,
                              request_id='fixture-intake-application', revision=context['revision'])
    assert receipt['saved'], receipt
    return receipt


def view(client, path, expected=200):
    response = client.get('/api/ui' + path)
    assert response.status_code == expected, response.text
    return response.json()['data']


def submit(client, identity, action, fields, *, csrf=True, origin=True):
    token = client.get('/api/ui/bootstrap').json()['csrf']
    headers = {}
    if origin:
        headers['Origin'] = ORIGIN
    if csrf:
        headers['X-CSRF-Token'] = token
    return client.post('/api/ui/intake/' + identity + '/' + action, json={'fields': fields}, headers=headers)


def follow(client, response):
    assert response.status_code == 200, response.text
    return view(client, response.json()['redirect'])


def test_intake_get_is_read_only_and_distinguishes_readiness(client, intake_source, monkeypatch):
    lib, hit, identity = intake_source
    from book_library import review_ai, intake
    monkeypatch.setattr(review_ai, 'suggest', lambda *_args, **_kwargs: pytest.fail('GET must never generate a review'))
    monkeypatch.setattr(intake, 'run_next', lambda *_: pytest.fail('GET must never run a queue job'))
    before = {path: path.read_bytes() for path in (lib.state / 'intakes').glob('*.json')}
    result = view(client, '/intake/' + identity)
    assert result['counts']['reviewed'] == result['counts']['total'] == 1
    assert result['job']['text_label'] == 'Ready'
    assert result['job']['semantic_label'] == 'Waiting to start'
    assert any(target['incomplete'] for target in result['target_page']['items'])
    assert {target['review_url'] for target in result['target_page']['items']} == {'/review/' + hit['work_id'], '/review/' + hit['section_id']}
    assert all(path.read_bytes() == value for path, value in before.items())
    assert not (lib.state / 'costs.jsonl').exists()
    assert view(client, '/intake')['listing']['items'][0]['url'] == '/intake/' + identity


def test_pause_and_resume_reject_stale_controls(client, intake_source):
    lib, _, identity = intake_source
    initial = view(client, '/intake/' + identity)
    stale = {'version': str(initial['job']['version'])}
    paused = follow(client, submit(client, identity, 'pause', stale))
    assert intake_status(lib, identity)['status'] == 'paused'
    assert 'Intake paused' in paused['message'] and paused['can_resume']
    rejected = submit(client, identity, 'pause', stale)
    assert rejected.status_code == 409
    assert 'Reload' in rejected.json()['data']['error']
    resumed = follow(client, submit(client, identity, 'resume', {'version': str(paused['job']['version'])}))
    assert intake_status(lib, identity)['status'] == 'queued'
    assert 'Intake resumed' in resumed['message']


@pytest.mark.parametrize('defect', ['csrf', 'origin', 'version'])
def test_intake_actions_are_protected(client, intake_source, defect):
    lib, _, identity = intake_source
    current = view(client, '/intake/' + identity)
    fields = {} if defect == 'version' else {'version': str(current['job']['version'])}
    response = submit(client, identity, 'pause', fields, csrf=defect != 'csrf', origin=defect != 'origin')
    assert response.status_code == (409 if defect == 'version' else 403)
    assert intake_status(lib, identity)['status'] == 'running'


def test_many_heading_outcomes_are_paginated_and_questions_are_easy_to_find(client, intake_source):
    lib, hit, identity = intake_source
    with writer(lib.state):
        job = _load(lib, identity)
        job['targets'] = [{'id': 'section_' + str(index), 'work_id': hit['work_id'], 'scope': 'section',
                          'title': f'Heading {index}', 'status': 'needs_evidence' if index % 1000 == 0 else 'no_change'} for index in range(5001)]
        _save(lib, job)
    result = view(client, '/intake/' + identity)
    assert len(result['target_page']['items']) == 25
    assert result['target_page']['total'] == 5001
    assert result['target_page']['start'] == 1 and result['target_page']['end'] == 25
    questions = view(client, '/intake/' + identity + '?view=attention')
    assert len(questions['target_page']['items']) == 6
    assert questions['view'] == 'attention'
    assert questions['target_page']['items'][-1]['title'] == 'Heading 5000'
    second = view(client, result['target_page']['next_url'])
    assert second['target_page']['start'] == 26 and second['target_page']['end'] == 50
    assert all(target['title'] != 'Heading 0' for target in second['target_page']['items'])


def test_source_and_model_text_remains_data_and_review_links_are_reconstructed(client, intake_source):
    lib, _, identity = intake_source
    with writer(lib.state):
        job = _load(lib, identity)
        job['work_titles'] = ['<script>unsafe title</script>']
        job['reason'] = '<img src=x onerror=alert(1)>'
        job['targets'][1].update(title='<svg onload=alert(1)>', review_url='javascript:alert(1)')
        _save(lib, job)
    response = client.get('/api/ui/intake/' + identity)
    assert response.headers['content-type'].startswith('application/json')
    result = response.json()['data']
    assert result['job']['display_title'] == '<script>unsafe title</script>'
    assert result['target_page']['items'][1]['title'] == '<svg onload=alert(1)>'
    assert result['target_page']['items'][1]['review_url'].startswith('/review/')


def test_individual_undo_preserves_metadata_semantics(client, intake_source):
    lib, hit, identity = intake_source
    automatic_title(intake_source)
    result = view(client, '/intake/' + identity)
    change = next(change for change in result['change_page']['items'] if change['undoable'])
    undone = follow(client, submit(client, identity, 'undo', {'version': str(result['job']['version']), 'event_id': change['event_id']}))
    assert '1 automatic change undone' in undone['message']
    context = lib.review_context(hit['section_id'])
    assert next(field for field in context['fields'] if field['key'] == 'bibliography.title')['raw_value'] is None
    assert undone['change_page']['items'][0]['status_label'] == 'Undone'


def test_bulk_undo_reports_protected_later_edits(client, intake_source):
    lib, hit, identity = intake_source
    automatic_title(intake_source)
    result = view(client, '/intake/' + identity)
    fields = {'version': str(result['job']['version'])}
    lib.annotate(hit['section_id'], {'field': 'bibliography', 'value': {'title': 'My own citation title'},
                                   'origin': 'user', 'status': 'confirmed', 'evidence': 'My explicit edit.'})
    after = follow(client, submit(client, identity, 'undo', fields))
    assert 'later edits are protected' in after['skipped'][0]['reason']
    assert next(field for field in lib.review_context(hit['section_id'])['fields'] if field['key'] == 'bibliography.title')['value'] == 'My own citation title'


def test_invalid_intake_and_navigation_do_not_mutate_state(client, intake_source):
    lib, _, identity = intake_source
    before = deepcopy(intake_status(lib, identity))
    for path in ['/intake/intake_missing', '/intake/' + identity + '?work=work_not_here', '/intake/' + identity + '?view=unrecognized']:
        assert client.get('/api/ui' + path).status_code == 404
    assert client.get('/api/ui/intake/' + identity + '?offset=-1').status_code == 400
    assert submit(client, identity, 'invented', {}).status_code == 404
    assert intake_status(lib, identity) == before


def test_empty_intake_list_does_not_queue_existing_books(tmp_path):
    from book_library.service import Library
    lib = Library(tmp_path)
    with TestClient(create_app(lib), base_url=ORIGIN) as client:
        result = view(client, '/intake')
    assert result['listing']['total'] == 0 and result['listing']['items'] == []
    assert not lib.state.exists()


def test_paid_queue_pause_identifies_the_intake_that_needs_resuming(client, intake_source):
    lib, _, identity = intake_source
    with writer(lib.state):
        blocker = deepcopy(_load(lib, identity))
        blocker.update(id='intake_budget_fixture', status='paused', reason_code='budget',
                       reason='The shared monthly allowance is exhausted.')
        _save(lib, blocker)
    result = view(client, '/intake/' + identity)
    assert result['job']['paid_blocked_by']['id'] == 'intake_budget_fixture'
    listing = view(client, '/intake')['listing']['items']
    assert next(job for job in listing if job['id'] == identity)['paid_blocked_by']['id'] == 'intake_budget_fixture'


def test_completed_reviews_offer_only_a_semantic_retry_when_indexing_is_pending(client, intake_source):
    lib, _, identity = intake_source
    with writer(lib.state):
        job = _load(lib, identity)
        job.update(status='complete', stage='complete')
        original_targets = deepcopy(job['targets'])
        _save(lib, job)
    result = view(client, '/intake/' + identity)
    assert result['retry_semantic'] and result['can_resume']
    resumed = follow(client, submit(client, identity, 'resume', {'version': str(result['job']['version'])}))
    assert 'Completed heading reviews are kept' in resumed['message']
    job = intake_status(lib, identity)
    assert job['stage'] == 'semantic' and job['status'] == 'queued'
    assert job['targets'] == original_targets


def test_source_discrepancies_and_possible_duplicates_stay_visible(client, intake_source):
    lib, hit, identity = intake_source
    with writer(lib.state):
        job = _load(lib, identity)
        job.update(source_label='Publisher download', duplicate_candidates=[hit['work_id']],
                   discrepancies=[{'reason': 'The supplied record names another edition.'}])
        _save(lib, job)
    result = view(client, '/intake/' + identity)
    assert 'another edition' in result['discrepancies'][0]
    assert result['duplicate_links'][0]['url'] == '/books/' + hit['work_id']
    assert result['job']['source_label'] == 'Publisher download'


def test_empty_accounted_heading_is_not_reported_as_missing_text():
    from book_library.intake_web import _target
    target = {'id': 'section_empty', 'scope': 'section', 'status': 'non_substantive',
              'coverage': {'target_blocks_total': 0, 'target_blocks_supplied': 0, 'complete': False}}
    assert not _target(target)['incomplete']
    target.update(status='incomplete', coverage={'target_blocks_total': 50, 'target_blocks_supplied': 10, 'complete': False})
    assert _target(target)['incomplete']
