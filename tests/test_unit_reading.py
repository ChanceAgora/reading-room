import json
from urllib.parse import urlparse, parse_qs
from zipfile import ZipFile

import pytest

from test_service import docx, seed


def unit_book(tmp_path):
    path = docx(tmp_path / 'books' / 'Reader' / 'book.docx', [
        ('Heading1', 'Chapter 1'), 'Opening argument. ' * 150,
        ('Heading2', 'An internal heading'), 'Further argument. ' * 150,
        'A late paragraph with naïve café and a distinctive goldfinch observation.',
        ('Heading1', 'Chapter 2'), 'The next independent chapter.',
    ])
    lib = seed(tmp_path / 'books', [{'title': 'Reading Research', 'paths': [path]}])
    wid = lib.books()[0]['id']
    with lib._db() as db:
        units = [dict(r) for r in db.execute('SELECT * FROM reading_units WHERE work_id=? ORDER BY ordinal', (wid,))]
    return lib, wid, units


def test_reader_opens_complete_chapter_with_nested_subheadings(tmp_path):
    lib, wid, units = unit_book(tmp_path)
    chapter = next(u for u in units if u['title'] == 'Chapter 1')
    reading = lib.read_unit(chapter['id'])
    text = '\n'.join(b['text'] for b in reading['blocks'])
    assert 'Opening argument.' in text and 'Further argument.' in text and 'goldfinch' in text
    assert 'next independent chapter' not in text
    assert reading['next']['title'] == 'Chapter 2'
    assert reading['next_cursor'] is None
    headings = [b for b in reading['blocks'] if b['kind'] == 'heading']
    assert [b['heading_depth'] for b in headings] == [2, 3]
    assert len({b['passage_id'] for b in reading['blocks']}) > 2


def test_search_coordinates_land_in_full_unit_without_losing_earlier_text(tmp_path):
    lib, wid, _ = unit_book(tmp_path)
    hit = lib.search('"distinctive goldfinch"', engine='exact', filters={'book': wid})['direct'][0]
    assert hit['read_url'].startswith('/units/')
    params = parse_qs(urlparse(hit['read_url']).query)
    reading = lib.read_unit(hit['unit_id'], match={'passage_id': params['match'][0], 'start': int(params['start'][0]), 'end': int(params['end'][0])})
    assert reading['cursor'] == 0
    assert 'Opening argument.' in '\n'.join(b['text'] for b in reading['blocks'])
    assert reading['anchor'] == hit['source_ranges'][0]['block_id']
    selected = {b['id']: b['text'] for b in reading['blocks']}
    quote = '\n\n'.join(selected[r['block_id']][r['start']:r['end']] for r in reading['source_ranges'])
    assert 'naïve café' in quote and 'distinctive goldfinch' in quote


def test_continuation_is_explicit_and_covers_entire_unit(tmp_path):
    lib, _, units = unit_book(tmp_path)
    unit = next(u for u in units if u['title'] == 'Chapter 1')
    full = lib.read_unit(unit['id'])
    actual = {}; cursor = 0; seen = set()
    while True:
        assert cursor not in seen
        seen.add(cursor)
        page = lib.read_unit(unit['id'], cursor=cursor, max_chars=500)
        for b in page['blocks']:
            actual[b['id']] = actual.get(b['id'], '') + b['text']
        if page['next_cursor'] is None:
            break
        cursor = page['next_cursor']
    assert actual == {b['id']: b['text'] for b in full['blocks']}
    with pytest.raises(ValueError, match='beyond'):
        lib.read_unit(unit['id'], cursor=full['total_chars'] + 1)


def test_grouped_contents_pagination_preserves_ancestor_context(tmp_path):
    lib, wid, _ = unit_book(tmp_path)
    pages = []; offset = 0; seen = set()
    while True:
        assert offset not in seen
        seen.add(offset)
        page = lib.contents(wid, offset=offset, limit=1)
        pages.append(page)
        if page['next_offset'] is None:
            break
        offset = page['next_offset']
    assert any(n.get('continued') for p in pages for n in p['nodes'])
    def flatten(nodes):
        return [item for n in nodes for item in [n, *flatten(n['children'])]]
    ids = [n['id'] for p in pages for n in flatten(p['nodes']) if not n['continued']]
    assert len(ids) == len(set(ids)) == pages[0]['total_nodes']


def test_direct_section_lookup_is_independent_of_contents_page(tmp_path):
    lib, wid, units = unit_book(tmp_path)
    target = json.loads(units[-1]['data'])['root_section_id']
    assert lib.section(target, wid)['title'] == 'Chapter 2'
    with pytest.raises(ValueError):
        lib.section(target, 'work_not_this_book')


def test_search_anchor_inside_long_source_block_opens_matching_continuation(tmp_path):
    path = docx(tmp_path / 'books' / 'Long' / 'book.docx', [
        ('Heading1', 'Long chapter'), 'opening ' * 200 + '🌿 exact target ' + 'closing ' * 100,
    ])
    lib = seed(tmp_path / 'books', [{'title': 'Long Reading', 'paths': [path]}])
    with lib._db() as db:
        unit_id = db.execute("SELECT id FROM reading_units WHERE title='Long chapter'").fetchone()[0]
    full = lib.read_unit(unit_id)
    block = next(b for b in full['blocks'] if 'exact target' in b['text'])
    offset = block['text'].index('🌿')
    reading = lib.read_unit(unit_id, anchor=block['id'], anchor_offset=offset, max_chars=500)
    assert reading['blocks'][0]['source_char_start'] == offset
    assert reading['blocks'][0]['text'].startswith('🌿 exact target')
    assert reading['cursor'] > 0 and reading['previous_cursor'] is not None
    with pytest.raises(ValueError, match='outside'):
        lib.read_unit(unit_id, anchor=block['id'], anchor_offset=len(block['text']) + 1)
    with pytest.raises(ValueError, match='not a member'):
        lib.read_unit(unit_id, anchor='block_unknown')


def test_page_marker_navigation_resolves_only_members_and_keeps_continuation(tmp_path):
    from book_library.service import Library
    from book_library.web import create_app
    from fastapi.testclient import TestClient

    root = tmp_path / 'books'
    root.mkdir()
    source = root / 'Page markers.epub'
    with ZipFile(source, 'w') as archive:
        archive.writestr('mimetype', 'application/epub+zip')
        archive.writestr('META-INF/container.xml', '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="EPUB/package.opf" media-type="application/oebps-package+xml"/></rootfiles></container>')
        archive.writestr('EPUB/package.opf', '<package xmlns="http://www.idpf.org/2007/opf" version="3.0"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Page markers</dc:title></metadata><manifest><item id="body" href="body.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="body"/></spine></package>')
        body = ('<span epub:type="pagebreak" id="start" title="1"/><p>' + 'Opening argument. ' * 80 +
                '</p><span epub:type="pagebreak" id="middle" title="2"/><p>' + 'Later argument. ' * 80 +
                '</p><span epub:type="pagebreak" id="end" title="3"/><h1>Another chapter</h1>'
                '<span epub:type="pagebreak" id="foreign" title="4"/><p>A separate chapter.</p>')
        archive.writestr('EPUB/body.xhtml', '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><body>' + body + '</body></html>')
    original = source.read_bytes()
    lib = Library(root)
    lib.sync(semantic=False)
    with lib._db() as db:
        members = [(json.loads(row['data']), row['unit_id']) for row in db.execute(
            'SELECT b.data,ub.unit_id FROM blocks b JOIN unit_blocks ub ON ub.block_id=b.id ORDER BY ub.ordinal')]
    markers = {block['locator']['element_id']: (block['id'], unit) for block, unit in members if block['kind'] == 'pagebreak'}
    unit = markers['start'][1]
    first = next(block['id'] for block, owner in members if owner == unit and block['text'].startswith('Opening argument.'))
    later = next(block['id'] for block, owner in members if owner == unit and block['text'].startswith('Later argument.'))
    assert all(markers[key][1] == unit for key in ('start', 'middle', 'end'))
    assert markers['foreign'][1] != unit
    for name, expected in [('start', first), ('middle', later), ('end', later)]:
        reading = lib.read_unit(unit, anchor=markers[name][0], max_chars=500)
        assert reading['anchor'] == expected
        assert reading['blocks'][0]['id'] == expected
        assert all(block['kind'] != 'pagebreak' for block in reading['blocks'])
        if name != 'start':
            assert reading['cursor'] > 0 and reading['previous_cursor'] is not None
    with pytest.raises(ValueError, match='not a member'):
        lib.read_unit(unit, anchor=markers['foreign'][0])
    with pytest.raises(ValueError, match='not a member'):
        lib.read_unit(unit, anchor=markers['middle'][0], anchor_offset=1)
    with TestClient(create_app(lib, enable_intake_worker=False), base_url='http://127.0.0.1:18765') as client:
        response = client.get('/api/ui/units/' + unit, params={'anchor': markers['start'][0]})
        assert response.status_code == 200
        assert response.json()['data']['reading']['anchor'] == first
    assert source.read_bytes() == original


def test_new_legacy_passage_usage_is_explicitly_scoped(tmp_path):
    lib, _, units = unit_book(tmp_path)
    block = next(b for b in lib.read_unit(units[0]['id'])['blocks'] if b.get('passage_id'))
    event = lib.record_usage({'kind': 'inspected', 'passage_id': block['passage_id'], 'evidence': 'Explicit test action'})
    assert event['target_scope'] == 'passage' and event['target_id'] == block['passage_id']
