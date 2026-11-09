"""React boundary contracts exercised without real books, workers, or providers."""
from copy import deepcopy
import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from book_library.web import create_app
from book_library.ui_models import PAGE_ADAPTER
from test_service import docx, seed
from test_web import FakeLibrary
from test_unit_web import UnitLibrary

ORIGIN = "http://127.0.0.1:18765"


@pytest.fixture
def library():
    return UnitLibrary()


@pytest.fixture
def client(library):
    with TestClient(create_app(library, enable_intake_worker=False), base_url=ORIGIN) as client:
        yield client


def action(client, path, fields, **kwargs):
    csrf = client.get('/api/ui/bootstrap').json()['csrf']
    return client.post('/api/ui' + path, json={'fields': fields},
                       headers={'Origin': ORIGIN, 'X-CSRF-Token': csrf}, **kwargs)


def data(response, page=None, status=200):
    assert response.status_code == status, response.text
    payload = response.json()
    PAGE_ADAPTER.validate_python(payload)
    if page:
        assert payload['page'] == page
    assert 'csrf' not in payload['data'] and 'request' not in payload['data']
    return payload['data']


@pytest.mark.parametrize('path,page', [
    ('/', 'search'), ('/search?q=ritual', 'search'), ('/books', 'books'),
    ('/books/work-1', 'book'), ('/read/passage-1', 'read'), ('/units/unit-essay', 'unit'),
    ('/selections/selection-a', 'selection'), ('/cite/unit/unit-essay', 'unit_citation'),
    ('/cite/selection/selection-a', 'unit_citation'), ('/focus', 'focuses'),
    ('/focus/new', 'focus'), ('/focus/sunday-core/books', 'focus-books'),
    ('/metadata/work-1?work=work-1', 'metadata'), ('/history', 'history'), ('/status', 'status'),
])
def test_page_contracts_preserve_structured_data(client, library, path, page):
    result = data(client.get('/api/ui' + path), page)
    assert result is not None
    assert not any(name in {'sync', 'annotate', 'record_usage', 'create_selection'} for name, _ in library.calls)


def test_bootstrap_has_http_only_cookie_and_no_credentials(client):
    first = client.get('/api/ui/bootstrap')
    assert first.status_code == 200
    assert set(first.json()) == {'csrf'}
    token = first.json()['csrf']
    assert len(token) == 64
    assert client.get('/api/ui/bootstrap').json()['csrf'] == token
    cookie = first.headers['set-cookie']
    assert 'HttpOnly' in cookie and 'SameSite=strict' in cookie and 'Path=/' in cookie
    assert first.headers['cache-control'] == 'no-store'


@pytest.mark.parametrize('defect', ['origin', 'token', 'missing-token', 'host'])
def test_json_mutations_keep_local_csrf_boundary(client, library, defect):
    csrf = client.get('/api/ui/bootstrap').json()['csrf']
    headers = {'Origin': ORIGIN, 'X-CSRF-Token': csrf}
    if defect == 'origin':
        headers['Origin'] = 'https://example.com'
    if defect == 'token':
        headers['X-CSRF-Token'] = '0' * 64
    if defect == 'missing-token':
        headers.pop('X-CSRF-Token')
    if defect == 'host':
        headers['Host'] = 'evil.example'
    response = client.post('/api/ui/sync', json={'fields': {}}, headers=headers)
    assert response.status_code == (400 if defect == 'host' else 403)
    assert set(response.json()) == {'error'}
    assert not library.calls


@pytest.mark.parametrize('payload', [
    {'fields': {'q': 42}}, {'fields': {'q': {'text': 'a'}}},
    {'fields': {'q': ['valid', False]}}, {'fields': {}, 'unexpected': True},
    {'fields': {str(i): 'a' for i in range(201)}}, [], None,
])
def test_action_schema_rejects_invalid_fields_without_work(client, library, payload):
    csrf = client.get('/api/ui/bootstrap').json()['csrf']
    response = client.post('/api/ui/search', json=payload,
                           headers={'Origin': ORIGIN, 'X-CSRF-Token': csrf})
    assert response.status_code in (400, 415)
    assert not library.calls


def test_bounded_stream_rejects_chunked_body(client, library):
    csrf = client.get('/api/ui/bootstrap').json()['csrf']
    def chunks():
        yield b'{"fields":{"q":"'
        for _ in range(10):
            yield b'a' * 4096
        yield b'"}}'
    response = client.post('/api/ui/search', content=chunks(),
                           headers={'Origin': ORIGIN, 'X-CSRF-Token': csrf, 'Content-Type': 'application/json'})
    assert response.status_code == 413
    assert not library.calls


def test_search_requires_explicit_post_for_combined_and_returns_data(client, library):
    response = action(client, '/search', {'q': 'ritual', 'mode': 'exploratory'})
    result = data(response, 'search')
    assert result['result']['direct'][0]['id'] == 'passage-1'
    assert 'html' not in response.json()
    assert library.calls[-1][0] == 'search'
    assert 'engine' not in library.calls[-1][1]
    before = len(library.calls)
    restored = data(client.get('/api/ui/search?q=ritual'), 'search')
    assert restored['q'] == 'ritual' and restored['result'] is None
    assert len(library.calls) == before
    action(client, '/search', {'q': 'ritual', 'engine': 'exact'})
    assert library.calls[-1][1]['engine'] == 'exact'


@pytest.mark.parametrize('path', ['/api/ui/', '/api/ui/search'])
@pytest.mark.parametrize('query', ['a saved research question', '<img src=x onerror=alert(1)>'])
def test_search_deep_link_only_restores_form_without_executing(client, library, path, query):
    response = client.get(path, params={'q': query, 'focus': 'sunday-core', 'mode': 'exploratory',
                                        'author': 'A. Reader', 'text_type': 'poem', 'engine': 'openai'})
    restored = data(response, 'search')
    assert restored['q'] == query
    assert restored['selected_focus'] == 'sunday-core'
    assert restored['filters']['author'] == 'A. Reader'
    assert restored['filters']['text_type'] == 'poem'
    assert restored['result'] is None
    assert 'Choose Search' in restored['message']
    assert not any(name == 'search' for name, _ in library.calls)


def test_legacy_search_get_preserves_exact_api_contract(client, library):
    response = client.get('/api/search', params={'q': 'ritual'})
    assert response.status_code == 200
    assert 'direct' in response.json() and 'page' not in response.json()
    assert library.calls[-1][1]['engine'] == 'exact'


def test_catalog_retains_sort_pagination_and_existing_list_api(client, library):
    listing = data(client.get('/api/ui/books?sort=creator'), 'books')
    assert listing['result']['total'] == 1
    assert listing['sort'] == 'creator'
    assert isinstance(client.get('/api/books').json(), list)
    assert client.get('/api/ui/books?sort=unknown').status_code == 400


def test_unit_selection_resolves_source_anchor_without_recording_use(client, library):
    reading = data(client.get('/api/ui/units/unit-essay?selection=selection-a'), 'unit')['reading']
    assert reading['selection']['quotation'] == '🌿 luminous'
    assert reading['anchor'] == 'block-a'
    assert any(call == ('read_unit', {'unit_id': 'unit-essay', 'anchor': 'block-a', 'cursor': 0, 'match': None}) for call in library.calls)
    assert '<script>not executable</script>' in reading['blocks'][1]['text']
    assert not any(name in {'create_selection', 'record_target_usage'} for name, _ in library.calls)


def test_unavailable_selection_is_conflict_not_relocated(client, library):
    existing = library.selection
    library.selection = lambda value: {**existing(value), 'available': False, 'error': 'Source changed.'}
    result = client.get('/api/ui/units/unit-essay?selection=selection-a')
    assert result.status_code == 409
    assert result.json()['error'] == 'Source changed.'
    assert not library.calls


def test_selection_and_usage_actions_keep_distinct_explicit_steps(client, library):
    ranges = [{'block_id': 'block-a', 'start': 2, 'end': 12}]
    result = action(client, '/selections', {'unit_id': 'unit-essay', 'source_ranges': json.dumps(ranges), 'action': 'cite'})
    assert result.json() == {'redirect': '/selections/selection-a?action=cite'}
    assert library.calls[-1] == ('create_selection', {'unit_id': 'unit-essay', 'ranges': ranges})
    assert not any(name == 'record_target_usage' for name, _ in library.calls)
    result = action(client, '/usage/target', {'scope': 'selection', 'target_id': 'selection-a', 'kind': 'used', 'purpose': 'efm', 'notes': 'A specific research use.'})
    assert result.status_code == 200
    assert result.json()['redirect'].startswith('/selections/selection-a')
    assert library.calls[-1][1]['event']['kind'] == 'used'


def test_focus_save_and_visible_book_selection_preserve_unseen_books(client, library):
    library.focus_items[0]['books'] = ['not-on-this-page']
    result = action(client, '/focus/sunday-core/books', {'books': ['work-1'], 'q': '', 'sort': 'title', 'offset': '0'})
    assert result.json()['redirect'].startswith('/focus/sunday-core/books?')
    assert library.focus_items[0]['books'] == ['not-on-this-page', 'work-1']
    response = action(client, '/focus/sunday-core', {'name': 'Revised focus', 'description': 'Carefully read', 'breadth': 'focused', 'subjects': 'poetry\nprayer', 'forms': ''})
    assert response.json() == {'redirect': '/focus/sunday-core?saved=true'}
    assert library.focus_items[0]['books'] == ['not-on-this-page', 'work-1']


@pytest.mark.parametrize('path', ['/api/not-real', '/api/ui/not-real', '/assets/not-real.js', '/not-real'])
def test_missing_routes_never_serve_spa_html(client, path):
    response = client.get(path)
    assert response.status_code == 404
    assert '<div id="root"' not in response.text


def test_schema_export_is_offline_and_contains_discriminated_page_types():
    app = create_app(object(), enable_intake_worker=False)
    schema = app.openapi()
    assert schema['components']['schemas']['UiPage']['discriminator']['propertyName'] == 'page'
    assert 'ReviewData' in schema['components']['schemas']
    assert '/api/ui/search' in schema['paths']
    assert 'application/json' in schema['paths']['/api/ui/search']['post']['requestBody']['content']


def test_built_shell_has_fresh_matching_nonce_without_loading_library(tmp_path):
    bundle = tmp_path / 'dist'
    (bundle / 'assets').mkdir(parents=True)
    (bundle / 'index.html').write_text('<!doctype html><html lang="en"><head><meta property="csp-nonce" nonce="__READING_ROOM_NONCE__"></head><body><div id="root"></div><script type="module" src="/assets/app.js" nonce="__READING_ROOM_NONCE__"></script></body></html>')
    (bundle / 'assets' / 'app.js').write_text('export const app = true;')
    (bundle / 'theme-init.js').write_text('/* local theme initialization */')
    library = FakeLibrary()
    with TestClient(create_app(library, enable_intake_worker=False, frontend_dir=bundle), base_url=ORIGIN) as client:
        first = client.get('/search?q=ritual')
        second = client.get('/books/work-1')
        assert first.status_code == second.status_code == 200
        assert '__READING_ROOM_NONCE__' not in first.text
        nonce = first.text.split('nonce="')[1].split('"')[0]
        assert f"'nonce-{nonce}'" in first.headers['content-security-policy']
        assert nonce not in second.text
        assert 'unsafe-inline' not in first.headers['content-security-policy']
        assert 'x-reading-room-nonce' not in first.headers
        assert client.get('/assets/app.js').status_code == 200
        assert client.get('/theme-init.js').status_code == 200
        assert client.get('/assets/missing.js').status_code == 404
        assert not library.calls


def test_missing_build_has_actionable_error_not_old_html(tmp_path):
    with TestClient(create_app(FakeLibrary(), enable_intake_worker=False, frontend_dir=tmp_path), base_url=ORIGIN) as client:
        response = client.get('/')
        assert response.status_code == 503
        assert 'npm --prefix frontend run build' in response.text
        assert client.get('/api/ui/status').status_code == 200
        assert client.get('/assets/missing.js').status_code == 404


@pytest.fixture
def source(tmp_path):
    root = tmp_path / 'books'
    path = docx(root / 'Fixture' / 'Source.docx', [
        ('Heading1', 'Publication'), 'A Book of Introductions', 'Edited by Jane Doe',
        'Example Press, 2024', ('Heading1', 'Introduction'),
        'Copper birds gather by the river.', '<script>source, never an executable</script>',
    ])
    library = seed(root, [{'title': 'A Book of Introductions', 'author': 'Jane Doe', 'paths': [path]}])
    hit = library.search('copper birds', engine='exact')['direct'][0]
    return library, hit, path


@pytest.fixture
def source_client(source):
    with TestClient(create_app(source[0], enable_intake_worker=False), base_url=ORIGIN) as client:
        yield client


def review_tokens(view):
    return {'revision': view['review']['revision'], 'version': str(view['draft']['version']), 'step': view['guided_step']}


def add_draft(client, target, field, value, **extra):
    current = data(client.get('/api/ui/review/' + target), 'review')
    return action(client, '/review/' + target + '/draft', {**review_tokens(current), 'field': field, 'value': value, 'evidence': 'Source heading in this fixture.', **extra})


@pytest.mark.parametrize('scope', ['work_id', 'section_id', 'id'])
def test_review_views_have_precomputed_fields_and_do_not_start_paid_work(source_client, source, monkeypatch, scope):
    library, hit, _ = source
    from book_library import review_ai
    monkeypatch.setattr(review_ai, 'suggest', lambda *_: pytest.fail('Reading cannot start paid work'))
    before = deepcopy(library._curation())
    view = data(source_client.get('/api/ui/review/' + hit[scope]), 'review')
    assert view['target']['id'] == hit[scope]
    assert view['field_map']['bibliography.title']['current_display']
    assert 'safe_link' not in view and 'display_value' not in view
    assert view['review']['revision'] == view['draft']['revision']
    assert library._curation() == before
    assert not (library.state / 'costs.jsonl').exists()


def test_review_drafts_conflicts_and_final_apply_are_preserved(source_client, source):
    library, hit, _ = source
    target = hit['section_id']
    before = deepcopy(library._curation())
    first = data(add_draft(source_client, target, 'bibliography.title', 'Revised title'), 'review')
    assert first['draft']['changes']['bibliography.title']['value'] == 'Revised title'
    assert library._curation() == before
    second = data(add_draft(source_client, target, 'bibliography.short_title', 'Revised'), 'review')
    old = action(source_client, '/review/' + target + '/draft', {**review_tokens(first), 'field': 'bibliography.title', 'value': 'Stale overwrite', 'evidence': ''})
    rejected = data(old, 'review', status=400)
    assert rejected['error']
    assert rejected['field_map']['bibliography.title']['edit_value'] == 'Stale overwrite'
    assert library.review_draft(target)['changes']['bibliography.title']['value'] == 'Revised title'
    fields = {**review_tokens(second), 'request_id': second['request_id'], 'count': '2',
              'field_0': 'bibliography.title', 'selected_0': 'yes', 'field_1': 'bibliography.short_title'}
    saved = data(action(source_client, '/review/' + target + '/apply', fields), 'review')
    assert saved['saved_fields'] == ['bibliography.title']
    assert library._curation()[-1]['status'] == 'provisional'
    assert 'bibliography.short_title' in library.review_draft(target)['changes']
    count = len(library._curation())
    data(action(source_client, '/review/' + target + '/apply', fields), 'review')
    assert len(library._curation()) == count


def test_review_editing_verified_draft_clears_verification(source_client, source):
    _, hit, _ = source
    target = hit['section_id']
    first = data(add_draft(source_client, target, 'bibliography.title', 'Verified title', verified='yes'), 'review')
    assert first['draft']['changes']['bibliography.title']['verified'] is True
    second = data(add_draft(source_client, target, 'bibliography.title', 'Changed title', verified='yes'), 'review')
    assert second['draft']['changes']['bibliography.title']['verified'] is False


def test_explicit_ai_request_is_replay_safe_and_keeps_manual_draft(source_client, source, monkeypatch):
    library, hit, _ = source
    target = hit['section_id']
    data(add_draft(source_client, target, 'bibliography.short_title', 'Keep this draft'), 'review')
    calls = []
    def generate(lib, context):
        calls.append(context['target']['id'])
        return {'status': 'complete', 'suggestions': [], 'unresolved': [], 'warnings': []}
    from book_library import review_ai
    monkeypatch.setattr(review_ai, 'suggest', generate)
    current = data(source_client.get('/api/ui/review/' + target), 'review')
    fields = {**review_tokens(current), 'generation_request_id': current['request_id']}
    data(action(source_client, '/review/' + target + '/suggest', fields), 'review')
    data(action(source_client, '/review/' + target + '/suggest', fields), 'review')
    assert calls == [target]
    assert library.review_draft(target)['changes']['bibliography.short_title']['value'] == 'Keep this draft'


def test_citation_preview_and_export_preserve_explicit_locator(source_client, source):
    library, hit, _ = source
    view = data(source_client.get('/api/ui/cite/' + hit['id']), 'citation')
    assert view['citation']['warnings']
    fields = {'locator_type': 'page', 'locator_value': '42–43', 'locator_verified': 'yes', 'locator_evidence': 'Verified in the fixture copy.'}
    preview = data(action(source_client, '/cite/' + hit['id'] + '/preview', fields), 'citation')
    assert preview['locator']['verified'] is True
    assert '42–43' in preview['citation']['full_note']
    downloaded = action(source_client, '/cite/' + hit['id'] + '/export', {**fields, 'format': 'json'})
    assert downloaded.status_code == 200
    assert downloaded.headers['content-disposition'].startswith('attachment;')
    assert downloaded.json()['full_note'] == preview['citation']['full_note']
    assert not (library.state / 'costs.jsonl').exists()


def test_intake_readiness_actions_and_conflict_remain_distinct(source_client, source, monkeypatch):
    library, hit, path = source
    from book_library.intake import enqueue_intake, _load, _save, intake_status
    from book_library.storage import writer
    from book_library import review_ai
    monkeypatch.setattr(review_ai, 'suggest', lambda *_: pytest.fail('Viewing intake cannot start paid work'))
    job = enqueue_intake(library, path.parent)
    with writer(library.state):
        job = _load(library, job['id'])
        job.update(status='running', work_ids=[hit['work_id']], work_titles=['A Book'],
                   readiness={'text': 'ready', 'semantic': 'pending'})
        _save(library, job)
    url = '/intake/' + job['id']
    view = data(source_client.get('/api/ui' + url), 'intake_detail')
    assert view['job']['text_label'] == 'Ready'
    assert view['job']['semantic_label'] == 'Waiting to start'
    assert view['can_pause'] is True
    version = str(view['job']['version'])
    response = action(source_client, url + '/pause', {'version': version})
    assert response.json()['redirect'].startswith(url)
    assert intake_status(library, job['id'])['status'] == 'paused'
    conflict = data(action(source_client, url + '/pause', {'version': version}), 'intake_detail', status=409)
    assert conflict['error']
    assert not (library.state / 'costs.jsonl').exists()
