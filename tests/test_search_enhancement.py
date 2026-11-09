"""Enhanced search shares rendering and security with native form submission."""
from fastapi.testclient import TestClient
from lxml import html
import pytest

from book_library.web import create_app
from test_web import FakeLibrary, ORIGIN


@pytest.fixture
def library():
    return FakeLibrary()


@pytest.fixture
def client(library):
    with TestClient(create_app(library), base_url=ORIGIN, raise_server_exceptions=False) as client:
        yield client


def enhanced(client, values=None, *, headers=None):
    fields = {'q': 'body', **(values or {})}
    csrf = fields.pop('csrf', client.get('/api/ui/bootstrap').json()['csrf'])
    return client.post('/api/ui/search', json={'fields': fields}, headers={'Origin': ORIGIN, 'X-CSRF-Token': csrf, **(headers or {})})


def test_search_returns_structured_source_data_and_explicit_query(client, library):
    library.hit['text'] = '<script>alert(1)</script> & a passage'
    query = '<img src=x onerror=alert(1)>'
    response = enhanced(client, {'q': query, 'book': 'work-1'})
    assert response.status_code == 200
    assert response.headers['content-type'].startswith('application/json')
    assert response.headers['cache-control'] == 'no-store'
    data = response.json()['data']
    assert data['q'] == query
    assert data['result']['direct'][0]['text'] == library.hit['text']
    assert 'html' not in data
    call = [options for name, options in library.calls if name == 'search'][-1]
    assert call['filters'] == {'book': 'work-1'}
    assert 'engine' not in call


@pytest.mark.parametrize('values, status, phrase', [
    ({'csrf': 'invalid'}, 403, 'expired'),
    ({'q': ''}, 400, 'research question'),
    ({'q': 'x' * 1501}, 400, '1,500'),
    ({'engine': 'anything'}, 400, 'combined or exact'),
    ({'mode': 'anything'}, 400, 'focused'),
])
def test_validation_errors_are_inline_json_without_searching(client, library, values, status, phrase):
    response = enhanced(client, values)
    assert response.status_code == status
    assert phrase in response.json()['error']
    assert not [call for call in library.calls if call[0] == 'search']


@pytest.mark.parametrize('headers, status', [
    ({'Origin': 'https://example.com'}, 403),
    ({'Content-Length': '40000'}, 413),
    ({'Host': 'example.com'}, 400),
])
def test_boundary_errors_use_json_and_security_headers(client, library, headers, status):
    response = enhanced(client, headers=headers)
    assert response.status_code == status
    assert set(response.json()) == {'error'}
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert response.headers['cache-control'] == 'no-store'
    assert not [call for call in library.calls if call[0] == 'search']


@pytest.mark.parametrize('exception, status', [(ValueError('private detail'), 400), (RuntimeError('private detail'), 500)])
def test_service_failures_are_recoverable_json_without_exception_details(client, library, exception, status):
    def fail(*args, **kwargs):
        raise exception
    library.search = fail
    response = enhanced(client)
    assert response.status_code == status
    assert 'error' in response.json()
    assert 'private detail' not in response.text
    assert response.headers['cache-control'] == 'no-store'


def test_empty_and_degraded_results_remain_successful_responses(client, library):
    original = library.search
    def empty(*args, **kwargs):
        result = original(*args, **kwargs)
        result['direct'] = []
        result['warnings'] = ['Meaning search is unavailable; showing exact matches only.']
        result['holdings_gap'] = 'No matching source surfaced.'
        return result
    library.search = empty
    response = enhanced(client)
    assert response.status_code == 200
    result = response.json()['data']['result']
    assert result['direct'] == []
    assert result['warnings'] == ['Meaning search is unavailable; showing exact matches only.']
    assert result['holdings_gap'] == 'No matching source surfaced.'


def test_ui_get_only_prefills_while_legacy_api_and_explicit_post_stay_exact(client, library):
    response = client.get('/api/ui/search?q=body', headers={'Accept': 'application/json'})
    assert response.json()['data']['result'] is None
    assert not any(name == 'search' for name, _ in library.calls)
    client.get('/api/search?q=body')
    enhanced(client, {'engine': 'exact'})
    searches = [options for name, options in library.calls if name == 'search']
    assert len(searches) == 2
    assert all(options['engine'] == 'exact' for options in searches)


def test_browser_reload_never_executes_search_on_server(client, library):
    # The React shell is data-independent, including previously submitted query URLs.
    # Result restoration and accessible feedback are covered in component/browser tests.
    client.get('/search?q=body&engine=openai')
    client.get('/search')
    assert not any(call[0] == 'search' for call in library.calls)
