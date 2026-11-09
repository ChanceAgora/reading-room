"""Public reader actions preserve scope and expose semantic source navigation."""
from copy import deepcopy
import json

from fastapi.testclient import TestClient
import pytest

from book_library.web import create_app
from test_web import FakeLibrary, ORIGIN


class UnitLibrary(FakeLibrary):
    def contents(self, work_id, offset=0, limit=100):
        leaf = {'id': 'section-essay', 'section_id': 'section-essay', 'title': 'Theological Perspective', 'depth': 3,
                'unit_id': 'unit-essay', 'children': [], 'attribution': 'B. Writer', 'attribution_verified': True}
        reading = {'id': 'section-reading', 'title': 'Jeremiah 15:15–21', 'depth': 2, 'children': [leaf]}
        day = {'id': 'section-day', 'title': 'Proper 17', 'depth': 1, 'children': [reading]}
        return {'work': deepcopy(self.work), 'nodes': [day], 'report': {'status': 'needs_review', 'issues': [{'message': 'One unresolved boundary remains.'}]},
                'offset': offset, 'next_offset': None, 'previous_offset': None}

    def section(self, section_id, work_id=None):
        return {'id': section_id, 'title': 'Far beyond the first contents page', 'profile': {}}

    def read_unit(self, unit_id, anchor=None, cursor=0, max_chars=200000, match=None, anchor_offset=0):
        self.calls.append(('read_unit', {'unit_id': unit_id, 'anchor': anchor, 'cursor': cursor, 'match': match}))
        return {'unit': {'id': unit_id, 'work_id': 'work-1', 'root_section_id': 'section-essay', 'title': 'Theological Perspective', 'kind': 'contribution', 'attribution': 'B. Writer', 'structure_status': 'supported'},
                'work': deepcopy(self.work), 'ancestors': [{'id': 'section-day', 'title': 'Proper 17'}, {'id': 'section-reading', 'title': 'Jeremiah 15:15–21'}],
                'blocks': [
                    {'id': 'block-a', 'text': 'A 🌿 luminous thought.', 'kind': 'paragraph', 'role': 'body', 'source_length': 21, 'source_char_start': 0, 'source_char_end': 21, 'note_links': [{'target_block_id': 'block-note', 'label': '1'}]},
                    {'id': 'block-b', 'text': '<script>not executable</script>', 'kind': 'paragraph', 'role': 'body', 'source_char_start': 0},
                    {'id': 'block-note', 'text': 'A verified source note.', 'kind': 'note', 'role': 'note', 'source_char_start': 0, 'backlinks': ['block-a']},
                ], 'previous': None, 'next': {'id': 'unit-next', 'title': 'Pastoral Perspective'},
                'next_cursor': None, 'previous_cursor': None, 'anchor': anchor, 'limitations': []}

    def create_selection(self, unit_id, ranges):
        self.calls.append(('create_selection', {'unit_id': unit_id, 'ranges': ranges}))
        return self.selection('selection-a')

    def selection(self, selection_id):
        return {'id': selection_id, 'unit_id': 'unit-essay', 'work_id': 'work-1', 'title': 'Theological Perspective', 'quotation': '🌿 luminous',
                'source_ranges': [{'block_id': 'block-a', 'start': 2, 'end': 12}]}

    def cite_unit(self, unit_id, locator=None):
        return {'target_scope': 'unit', 'full_note': 'Complete essay citation.', 'short_note': 'Writer, essay.', 'bibliography': 'Writer. Essay.', 'warnings': []}

    def cite_selection(self, selection_id, locator=None):
        return {'target_scope': 'selection', 'quotation': '🌿 luminous', 'full_note': 'Selected text citation.', 'short_note': 'Writer, selected text.', 'bibliography': 'Writer. Essay.', 'warnings': ['Printed page requires review.']}

    def record_target_usage(self, scope, target_id, event):
        self.calls.append(('record_target_usage', {'scope': scope, 'target_id': target_id, 'event': event}))
        return event


@pytest.fixture
def unit_client():
    library = UnitLibrary()
    with TestClient(create_app(library, enable_intake_worker=False), base_url=ORIGIN) as client:
        yield client, library


def ui_page(client, path, status=200):
    response = client.get('/api/ui' + path)
    assert response.status_code == status, response.text
    return response.json()['data'] if status == 200 else response.json()


def action(client, path, fields):
    csrf = client.get('/api/ui/bootstrap').json()['csrf']
    return client.post('/api/ui' + path, json={'fields': fields},
                       headers={'Origin': ORIGIN, 'X-CSRF-Token': csrf})


def test_contents_has_real_hierarchy_and_verified_authors(unit_client):
    # Rendering/disclosure/focus assertions now live in ReadingPages.test.tsx.
    client, _ = unit_client
    data = ui_page(client, '/books/work-1')
    day = data['outline']['nodes'][0]
    reading = day['children'][0]
    leaf = reading['children'][0]
    assert [item['title'] for item in [day, reading, leaf]] == [
        'Proper 17', 'Jeremiah 15:15–21', 'Theological Perspective']
    assert [item['depth'] for item in [day, reading, leaf]] == [1, 2, 3]
    assert leaf['unit_id'] == 'unit-essay'
    assert leaf['attribution'] == 'B. Writer' and leaf['attribution_verified']
    assert data['outline']['report']['issues'] == [{'message': 'One unresolved boundary remains.'}]


def test_complete_reader_preserves_source_coordinates_and_note_links(unit_client):
    client, library = unit_client
    reading = ui_page(client, '/units/unit-essay?anchor=block-a')['reading']
    assert [block['text'] for block in reading['blocks']] == [
        'A 🌿 luminous thought.', '<script>not executable</script>', 'A verified source note.']
    assert reading['anchor'] == 'block-a'
    assert reading['blocks'][0]['note_links'] == [{'target_block_id': 'block-note', 'label': '1'}]
    assert reading['blocks'][2]['backlinks'] == ['block-a']
    assert reading['blocks'][0]['source_char_start'] == 0
    assert reading['blocks'][0]['source_char_end'] == 21
    assert not any(name in ('create_selection', 'record_target_usage') for name, _ in library.calls)


def test_selection_post_requires_csrf_and_previews_before_citation(unit_client):
    client, library = unit_client
    values = {'unit_id': 'unit-essay', 'action': 'cite', 'source_ranges': json.dumps([{'block_id': 'block-a', 'start': 2, 'end': 12}])}
    assert client.post('/api/ui/selections', json={'fields': values}, headers={'Origin': ORIGIN}).status_code == 403
    response = action(client, '/selections', values)
    assert response.status_code == 200
    assert response.json()['redirect'] == '/selections/selection-a?action=cite'
    preview = ui_page(client, response.json()['redirect'])
    assert preview['action'] == 'cite'
    assert preview['selection']['quotation'] == '🌿 luminous'
    assert not any(name == 'record_target_usage' for name, _ in library.calls)
    assert next(data for name, data in library.calls if name == 'create_selection')['ranges'][0]['start'] == 2


def test_explicit_selection_use_has_selection_scope_without_client_credit(unit_client):
    client, library = unit_client
    result = action(client, '/usage/target', {'scope': 'selection', 'target_id': 'selection-a', 'kind': 'used', 'purpose': 'class-prep', 'notes': 'Used these exact words.', 'attribution': 'Forged creator'})
    assert result.status_code == 200
    assert result.json()['redirect'] == '/selections/selection-a?action=record&saved=true#research-record'
    event = next(data for name, data in library.calls if name == 'record_target_usage')
    assert event['scope'] == 'selection'
    assert event['target_id'] == 'selection-a'
    assert 'attribution' not in event['event']
    assert 'passage_id' not in event['event']


def test_new_citation_views_distinguish_unit_and_selection(unit_client):
    client, _ = unit_client
    complete = ui_page(client, '/cite/unit/unit-essay')
    assert complete['citation']['full_note'] == 'Complete essay citation.'
    assert complete['scope'] == 'unit'
    selected = ui_page(client, '/cite/selection/selection-a')
    assert selected['citation']['full_note'] == 'Selected text citation.'
    assert selected['citation']['warnings'] == ['Printed page requires review.']
    assert selected['scope'] == 'selection'
    assert selected['back_url'] == '/units/unit-essay?selection=selection-a'


def test_metadata_direct_lookup_is_independent_of_contents_page(unit_client):
    client, _ = unit_client
    data = ui_page(client, '/metadata/section-on-page-nine?work=work-1')
    assert data['target']['title'] == 'Far beyond the first contents page'


def test_search_match_coordinates_reach_unit_reader_without_text_matching(unit_client):
    client, library = unit_client
    ui_page(client, '/units/unit-essay?match=passage-1&start=2&end=12')
    reading = next(data for name, data in library.calls if name == 'read_unit')
    assert reading['match'] == {'passage_id': 'passage-1', 'start': 2, 'end': 12}


def test_unavailable_selection_keeps_saved_words_without_relocating_source(unit_client, monkeypatch):
    client, library = unit_client
    original = library.selection
    monkeypatch.setattr(library, 'selection', lambda value: {**original(value), 'available': False, 'error': 'The source changed.'})
    selection = ui_page(client, '/selections/selection-a?action=record')['selection']
    assert selection['quotation'] == '🌿 luminous'
    assert selection['available'] is False
    assert selection['error'] == 'The source changed.'
    assert ui_page(client, '/units/unit-essay?selection=selection-a', status=409)['error'] == 'The source changed.'
    assert not any(name == 'read_unit' for name, _ in library.calls)


def test_real_service_outline_reader_selection_and_citation_agree(tmp_path):
    from test_unit_reading import unit_book
    lib, work_id, units = unit_book(tmp_path)
    unit_id = next(unit['id'] for unit in units if unit['title'] == 'Chapter 1')
    with TestClient(create_app(lib, enable_intake_worker=False), base_url=ORIGIN) as client:
        contents = ui_page(client, '/books/' + work_id)
        def walk(nodes):
            for node in nodes:
                yield node
                yield from walk(node.get('children', []))
        inner = next(node for node in walk(contents['outline']['nodes']) if node['title'] == 'An internal heading')
        assert inner['unit_id'] == unit_id and inner['anchor_block_id']
        reader = ui_page(client, '/units/' + unit_id + '?anchor=' + inner['anchor_block_id'])['reading']
        source_text = '\n'.join(block['text'] for block in reader['blocks'])
        assert 'Opening argument.' in source_text and 'distinctive goldfinch' in source_text
        reading = lib.read_unit(unit_id)
        block = next(block for block in reading['blocks'] if 'naïve café' in block['text'])
        start = block['text'].index('naïve')
        end = start + len('naïve café')
        response = action(client, '/selections', {'unit_id': unit_id, 'source_ranges': json.dumps([{'block_id': block['id'], 'start': start, 'end': end}]), 'action': 'cite'})
        assert response.status_code == 200
        destination = response.json()['redirect']
        preview = ui_page(client, destination)
        assert preview['selection']['quotation'] == 'naïve café'
        selection_id = destination.split('/')[2].split('?')[0]
        citation = ui_page(client, '/cite/selection/' + selection_id)
        assert citation['citation']['quotation'] == 'naïve café'
        assert ui_page(client, '/cite/unit/' + unit_id)['scope'] == 'unit'
        assert lib.usage() == []


def test_saved_selection_link_opens_the_exact_fragment_of_a_long_source_block(tmp_path):
    from test_service import docx, seed
    prefix = 'Extensive introductory argument. ' * 8000
    quote = '🌿 The precise words at the end.'
    path = docx(tmp_path / 'books' / 'Long book' / 'book.docx', [('Heading1', 'A long chapter'), prefix + quote])
    lib = seed(tmp_path / 'books', [{'title': 'Long Source', 'paths': [path]}])
    unit = lib.contents(lib.books()[0]['id'])['nodes'][0]['unit_id']
    block = next(block for block in lib.read_unit(unit, max_chars=500000)['blocks'] if block['kind'] != 'heading')
    saved = lib.create_selection(unit, [{'block_id': block['id'], 'start': len(prefix), 'end': len(prefix + quote)}])
    with TestClient(create_app(lib, enable_intake_worker=False), base_url=ORIGIN) as client:
        reading = ui_page(client, '/units/' + unit + '?selection=' + saved['id'])['reading']
        source = next(value for value in reading['blocks'] if value['id'] == block['id'])
        assert source['source_char_start'] == len(prefix)
        assert source['text'] == quote
        assert reading['previous_cursor'] is not None
        assert reading['selection']['source_ranges'] == saved['source_ranges']


def test_structural_review_preserves_all_findings_for_bounded_frontend_groups(unit_client, monkeypatch):
    # ReadingPages.test.tsx checks the four groups, bounded examples and escaping.
    client, library = unit_client
    issues = [{'code': 'navigation', 'message': 'Navigation target needs review.', 'label': '<script>source label</script>' if i == 0 else f'Source heading {i}'} for i in range(415)]
    issues += [{'code': 'ancestry', 'message': 'Parent heading is unresolved.'} for _ in range(312)]
    issues += ['An unclassified boundary.', 'An unclassified boundary.']
    issues += [{'code': 'different_evidence', 'message': 'Navigation target needs review.'}]
    original_contents, original_status = library.contents, library.status
    monkeypatch.setattr(library, 'contents', lambda *args, **kwargs: {**original_contents(*args, **kwargs), 'report': {'status': 'needs_review', 'issues': issues}})
    monkeypatch.setattr(library, 'status', lambda: {**original_status(), 'structure': {'supported': 0, 'needs_review': 1, 'review_books': [{'work_id': 'work-1', 'title': 'A source', 'issues': issues}]}})
    assert ui_page(client, '/books/work-1')['outline']['report']['issues'] == issues
    assert ui_page(client, '/status')['status']['structure']['review_books'][0]['issues'] == issues
    assert client.get('/api/contents/work-1').json()['report']['issues'] == issues
