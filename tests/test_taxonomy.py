from __future__ import annotations

from copy import deepcopy
import json
import sqlite3

from fastapi.testclient import TestClient
import pytest

from book_library.defaults import TAXONOMY
from book_library.service import Library
from book_library.storage import SCHEMA, atomic_json, read_json
from book_library.taxonomy import facet_books, get_term, list_taxonomy, save_term, term_id
from book_library.web import create_app

ORIGIN = 'http://127.0.0.1:8765'


@pytest.fixture
def library(tmp_path):
    lib = Library(tmp_path)
    (lib.state / 'generations').mkdir(parents=True)
    atomic_json(lib.state / 'taxonomy.json', deepcopy(TAXONOMY))
    dbpath = lib.state / 'generations' / 'fixture.sqlite3'
    db = sqlite3.connect(dbpath)
    db.executescript(SCHEMA)
    for id, title, available in [('one', 'First poem book', True), ('two', 'Missing book', False), ('three', 'Teaching book', True)]:
        book = {'id': id, 'title': title, 'author': 'Fixture editor', 'available': available, 'files': [{'id': 'file-' + id}]}
        db.execute('INSERT INTO works VALUES(?,?,?,?)', (id, title, book['author'], json.dumps(book)))
    for target, wid, field, value in [('one', 'one', 'subjects', 'poetry'), ('section-1', 'one', 'subjects', 'poetry'), ('two', 'two', 'subjects', 'poetry'), ('section-2', 'three', 'subjects', 'education'), ('section-3', 'one', 'forms', 'poem'), ('one', 'one', 'forms', 'poem'), ('three', 'three', 'themes', 'group trust')]:
        db.execute('INSERT INTO facets VALUES(?,?,?,?,?,?,?)', (target, wid, field, value, 'codex', 'provisional', 'Fixture evidence'))
    db.commit(); db.close()
    atomic_json(lib.state / 'current.json', {'generation': 'fixture', 'database': dbpath.name})
    return lib


def data(label, **kwargs):
    return {'label': label, 'evidence': 'Editorial decision after inspecting source context.', **kwargs}


def test_counts_distinct_available_works_across_section_and_book_facets(library):
    result = list_taxonomy(library)
    counts = {(x['facet'], x['value']): x['work_count'] for x in result['facets']}
    assert counts[('subjects', 'poetry')] == 1
    assert counts[('forms', 'poem')] == 1
    assert counts[('subjects', 'education')] == 1
    assert counts[('themes', 'group trust')] == 1
    assert [b['id'] for b in facet_books(library, 'subjects', 'education')['books']] == ['three']
    assert [b['id'] for b in facet_books(library, 'forms', 'poem')['books']] == ['one']
    assert facet_books(library, 'subjects', 'missing')['books'] == []


def test_bounded_alias_search_and_no_original_files(library, monkeypatch):
    def blocked(*args, **kwargs): raise AssertionError('Source inventory must not be opened to browse vocabulary.')
    monkeypatch.setattr(library, '_inventory', blocked)
    result = list_taxonomy(library, query='verse', limit=1)
    assert result['terms'][0]['id'] == 'poetry'
    assert len(list_taxonomy(library, limit=1)['facets']) == 1
    assert list_taxonomy(library, limit=1)['has_more']
    assert len(facet_books(library, 'subjects', 'poetry', limit=1)['books']) == 1


def test_no_index_still_allows_vocabulary_editing(tmp_path):
    lib = Library(tmp_path)
    result = list_taxonomy(lib)
    assert result['warning']
    assert result['terms']
    assert result['facets'] == []
    saved = save_term(lib, 'new-topic', data('A new topic'))
    assert saved['origin'] == 'user'
    assert get_term(lib, 'new-topic')['label'] == 'A new topic'


def test_relationships_are_resolved_by_names_and_kept_reciprocal(library):
    save_term(library, 'haiku', data('Haiku', broader=['Poetry'], related=['Ecology'], aliases=['hokku']))
    haiku = get_term(library, 'haiku')
    assert haiku['broader'] == ['poetry']
    assert haiku['related'] == ['ecology']
    assert 'haiku' in get_term(library, 'poetry')['narrower']
    assert 'haiku' in get_term(library, 'ecology')['related']
    save_term(library, 'haiku', data('Haiku', related=[]))
    assert 'haiku' not in get_term(library, 'ecology')['related']
    assert 'haiku' in get_term(library, 'poetry')['narrower']
    assert len(get_term(library, 'haiku')['history']) == 1
    assert 'history' not in list_taxonomy(library, query='haiku')['terms'][0]


def test_user_corrections_survive_generated_replacement_and_relationship_changes(library):
    save_term(library, 'poetry', data('Poetry', aliases=['verse', 'poems']))
    before = read_json(library.state / 'taxonomy.json')
    with pytest.raises(ValueError, match='user correction'):
        save_term(library, 'poetry', data('Poetry', aliases=['new name'], origin='codex'))
    with pytest.raises(ValueError, match='user-corrected'):
        save_term(library, 'haiku', data('Haiku', broader=['poetry'], origin='codex', status='provisional'))
    assert read_json(library.state / 'taxonomy.json') == before


@pytest.mark.parametrize('id,values,match', [
    ('../escape', data('Topic'), 'identifier'),
    ('topic', {'label': 'Topic'}, 'Evidence'),
    ('topic', data('Topic', aliases='wrong type'), 'Aliases'),
    ('topic', data('Topic', aliases=['same', 'Same']), 'duplicate'),
    ('topic', data('Topic', aliases=['verse']), 'already belongs'),
    ('topic', data('Topic', broader=['does not exist']), 'Create the vocabulary'),
    ('topic', data('Topic', related=['Topic']), 'itself'),
    ('topic', data('Topic', broader=['poetry'], narrower=['Poetry']), 'both broader'),
    ('topic', data('Topic', origin='system'), 'origin'),
])
def test_invalid_edits_do_not_write(library, id, values, match):
    before = (library.state / 'taxonomy.json').read_bytes()
    with pytest.raises(ValueError, match=match): save_term(library, id, values)
    assert (library.state / 'taxonomy.json').read_bytes() == before


def test_hierarchy_cycle_rejected_atomically(library):
    save_term(library, 'haiku', data('Haiku', broader=['poetry']))
    before = (library.state / 'taxonomy.json').read_bytes()
    with pytest.raises(ValueError, match='circular'):
        save_term(library, 'literature', data('Literature', broader=['haiku']))
    assert (library.state / 'taxonomy.json').read_bytes() == before


def test_generated_identifiers_work_for_diacritics_and_other_scripts():
    assert term_id('Spiritual Formation') == 'spiritual-formation'
    assert term_id('Oríkì') == 'oriki'
    assert term_id('知識').startswith('term-')


@pytest.fixture
def client(library):
    with TestClient(create_app(library), base_url=ORIGIN) as c: yield c


def token(client):
    return client.get('/api/ui/bootstrap').json()['csrf']


@pytest.mark.parametrize('path', ['/taxonomy', '/taxonomy?q=poetry', '/taxonomy/browse?facet=subjects&value=education', '/taxonomy/new', '/taxonomy/term/poetry'])
def test_vocabulary_views_have_structured_context_and_no_mutations(client, library, path):
    before = (library.state / 'taxonomy.json').read_bytes()
    response = client.get('/api/ui' + path)
    assert response.status_code == 200
    payload = response.json()
    assert payload['page'] in {'taxonomy', 'taxonomy_books', 'taxonomy_term'}
    assert payload['title'] and payload['nav'] == 'taxonomy'
    assert isinstance(payload['data'], dict)
    assert 'html' not in payload
    assert (library.state / 'taxonomy.json').read_bytes() == before


def test_vocabulary_search_preserves_unicode_query_in_view_model(client):
    query = 'Oríkì & poetry'
    response = client.get('/api/ui/taxonomy', params={'q': query})
    assert response.status_code == 200
    assert response.json()['data']['vocabulary']['query'] == query


@pytest.mark.parametrize('path,exclude', [('/taxonomy/new', ''), ('/taxonomy/term/poetry', 'poetry')])
def test_taxonomy_relationship_view_preserves_labels_and_term_ids(client, path, exclude):
    document = client.get('/api/ui' + path).json()['data']
    assert set(document['relation_labels']) == {'broader', 'narrower', 'related'}
    assert document['term'].get('id', '') == exclude
    if exclude:
        assert document['action'] == '/taxonomy/term/poetry'
        assert document['relation_labels']['broader'] == ['Literature']


def test_protected_vocabulary_save_preserves_unrelated_terms(client, library):
    before = get_term(library, 'history')
    values = {'label': 'Haiku', 'aliases': 'hokku', 'broader': 'Poetry', 'related': 'Ecology', 'evidence': 'A useful classification for short poems.'}
    csrf = token(client)
    assert client.post('/api/ui/taxonomy/new', json={'fields': values}, headers={'X-CSRF-Token': csrf}).status_code == 403
    assert client.post('/api/ui/taxonomy/new', json={'fields': values}, headers={'Origin': ORIGIN, 'X-CSRF-Token': 'bad'}).status_code == 403
    response = client.post('/api/ui/taxonomy/new', json={'fields': values}, headers={'Origin': ORIGIN, 'X-CSRF-Token': csrf})
    assert response.status_code == 200
    assert response.json()['redirect'] == '/taxonomy/term/haiku?saved=true'
    assert get_term(library, 'haiku')['broader'] == ['poetry']
    assert get_term(library, 'history') == before
    saved = client.get('/api/ui' + response.json()['redirect']).json()['data']
    assert saved['saved'] is True


def test_invalid_form_keeps_user_text_and_safe_error(client, library):
    values = {'label': 'New idea <script>bad()</script>', 'related': 'Unknown term', 'evidence': 'Keep this editorial reason.'}
    response = client.post('/api/ui/taxonomy/new', json={'fields': values}, headers={'Origin': ORIGIN, 'X-CSRF-Token': token(client)})
    assert response.status_code == 400
    document = response.json()['data']
    assert document['term']['label'] == values['label']
    assert document['term']['evidence'] == values['evidence']
    assert document['error']
    assert response.headers['content-type'].startswith('application/json')


def test_duplicate_creation_does_not_overwrite_existing_term(client, library):
    before = get_term(library, 'poetry')
    response = client.post('/api/ui/taxonomy/new', json={'fields': {'label': 'Poetry', 'evidence': 'Attempted duplicate.'}}, headers={'Origin': ORIGIN, 'X-CSRF-Token': token(client)})
    assert response.status_code == 400
    assert 'already exists' in response.text
    assert get_term(library, 'poetry') == before
