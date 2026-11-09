"""A flattened EPUB must not turn an entire anthology into front matter."""

import copy
import gzip
import json
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZipFile

import pytest

from book_library import service
from book_library.extract import extract_file
from test_service import seed, annotate


SOURCE_SHA = '2ef814f8eb5f5ca424a64cc949171d686c754b2187c8325e60da34bb0fe985a6'
PART1 = 'EPUB/A_Book_of_Luminous_Things-1.xhtml'
PART2 = 'EPUB/A_Book_of_Luminous_Things-2.xhtml'
# Only structural labels from the inspected source; all prose below is synthetic.
HEADINGS = [
    (PART1, 'p_00014', 'ACKNOWLEDGMENTS', 'v'),
    (PART1, 'p_00018', 'CONTENTS', 'VII'),
    (PART1, 'p_00229', 'INTRODUCTION', 'XV'),
    (PART2, 'p_000019', 'Epiphany', '4'),
    (PART2, 'p_000068', 'Nature', '9'),
    (PART2, 'p_000495', 'The Secret of a Thing', '49'),
    (PART2, 'p_000705', 'Travel', '73'),
    (PART2, 'p_001060', 'Places', '105'),
    (PART2, 'p_001384', 'The Moment', '137'),
    (PART2, 'p_001745', 'People Among People', '175'),
    (PART2, 'p_002115', "Woman's Skin", '211'),
    (PART2, 'p_002380', 'Situations', '237'),
    (PART2, 'p_002563', 'Nonattachment', '261'),
    (PART2, 'p_002882', 'History', '291'),
    (PART2, 'p_003049', 'PERMISSIONS', '307'),
    (PART2, 'p_003161', 'INDEX OF AUTHORS', '315'),
    (PART2, 'p_003241', 'INDEX OF TITLES OR FIRST LINES', '317'),
]


def flattened_epub(tmp_path):
    path = tmp_path / 'books' / 'Anthology' / 'flattened.epub'
    path.parent.mkdir(parents=True)
    bodies = {PART1: '<p>Publisher title and imprint.</p>', PART2: '<p>Introduction continued across spine members.</p>'}
    for member, anchor, title, page in HEADINGS:
        bodies[member] += (f'<span epub:type="pagebreak" title="{page}"/>'
                           f'<p id="{anchor}" xml:space="preserve">{escape(title)}</p>'
                           f'<p>Sample text within {escape(title)}.</p>')
        if title == 'Nature':
            bodies[member] += '<p id="not-a-heading">A CAPITALIZED POEM LINE</p><p>A Person Name</p>'
    with ZipFile(path, 'w') as archive:
        archive.writestr('mimetype', 'application/epub+zip')
        archive.writestr('META-INF/container.xml', '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="EPUB/package.opf"/></rootfiles></container>')
        archive.writestr('EPUB/package.opf', '<package xmlns="http://www.idpf.org/2007/opf" version="3.0"><manifest>' + ''.join(
            f'<item id="p{i}" href="{Path(member).name}" media-type="application/xhtml+xml"/>' for i, member in enumerate(bodies)) +
            '</manifest><spine><itemref idref="p0"/><itemref idref="p1"/></spine></package>')
        for member, body in bodies.items():
            archive.writestr(member, '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><body>' + body + '</body></html>')
    return path


def test_flattened_anthology_sections_survive_sync_and_curation(tmp_path, monkeypatch):
    path = flattened_epub(tmp_path)
    original = path.read_bytes()
    real_digest = service.digest
    # Identify this synthetic structural fixture as the inspected edition.
    monkeypatch.setattr(service, 'digest', lambda p: SOURCE_SHA if Path(p) == path else real_digest(p))
    lib = seed(tmp_path / 'books', [{'title': 'Anthology', 'paths': [path],
                                   'metadata': {'editors': ['Volume Editor']}}])
    work_id = lib.books()[0]['id']
    book = lib.book(work_id)
    assert [s['title'] for s in book['sections']] == ['Front matter'] + [h[2] for h in HEADINGS]
    nature = next(s for s in book['sections'] if s['title'] == 'Nature')
    with lib._db() as db:
        blocks = [json.loads(r[0]) for r in db.execute('SELECT data FROM blocks ORDER BY ordinal')]
        attribution = db.execute('SELECT attribution FROM passages WHERE section_id=?', (nature['id'],)).fetchone()[0]
    assert attribution.startswith('Contributor unverified; edited by ')
    source = extract_file(path)['blocks']
    assert [(b['text'], b['locator']) for b in blocks] == [(b['text'], b['locator']) for b in source]
    epiphany = next(b for b in blocks if b['text'] == 'Epiphany')
    assert epiphany['locator']['page'] == '4'  # Do not silently repair defective source pagination.
    assert epiphany['heading_evidence']['origin'] == 'reviewed_source_structure'
    assert next(b for b in blocks if b['text'] == 'A CAPITALIZED POEM LINE')['kind'] == 'paragraph'
    assert next(b for b in blocks if b['text'] == 'A CAPITALIZED POEM LINE')['heading_path'] == ['Nature']
    assert next(b for b in blocks if b['text'].startswith('Introduction continued'))['heading_path'] == ['INTRODUCTION']
    annotate(lib, nature['id'], 'My Nature label', field='title')
    history = (lib.state / 'curation.jsonl').read_bytes()
    lib.sync(rebuild=True)
    again = lib.book(work_id)
    assert next(s for s in again['sections'] if s['id'] == nature['id'])['title'] == 'My Nature label'
    assert (lib.state / 'curation.jsonl').read_bytes() == history
    assert path.read_bytes() == original
    # Raw extraction remains a faithful record; the reviewed structure is an index overlay.
    file = next(iter(lib._catalog()['files'].values()))
    with gzip.open(lib.state / 'extractions' / file['cache'], 'rt') as inp:
        cached = json.load(inp)
    assert all(b['kind'] != 'heading' for b in cached['blocks'])


def test_same_labels_in_unreviewed_source_are_not_headings(tmp_path):
    from book_library.source_structure import apply_reviewed_structure

    extraction = extract_file(flattened_epub(tmp_path))
    before = copy.deepcopy(extraction)
    apply_reviewed_structure({'sha256': 'different-edition'}, extraction)
    assert extraction == before


@pytest.mark.parametrize('damage', ['missing', 'duplicate', 'changed_text', 'changed_member', 'out_of_order', 'boilerplate', 'note'])
def test_ambiguous_or_changed_boundaries_leave_text_unmodified(tmp_path, damage):
    from book_library.source_structure import apply_reviewed_structure

    extraction = extract_file(flattened_epub(tmp_path))
    blocks = extraction['blocks']
    target = next(b for b in blocks if b['text'] == 'Nature')
    if damage == 'missing':
        blocks.remove(target)
    elif damage == 'duplicate':
        blocks.append(copy.deepcopy(target))
    elif damage == 'changed_text':
        target['text'] = 'A different heading'
    elif damage == 'changed_member':
        target['locator']['member'] = 'EPUB/other.xhtml'
    elif damage == 'out_of_order':
        blocks.remove(target)
        blocks.append(target)
    elif damage == 'boilerplate':
        target['is_boilerplate'] = True
    elif damage == 'note':
        target['locator']['note_id'] = 'n1'
    before = copy.deepcopy(blocks)
    apply_reviewed_structure({'sha256': SOURCE_SHA}, extraction)
    assert blocks == before
    assert extraction['warnings'] == ['Reviewed section boundaries no longer match the extraction; structure requires source review.']
