"""Source evidence, whole-work ancestry, and explicit reading membership."""
from copy import deepcopy
import gzip
import json
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from book_library.extract import extract_file
from book_library.structure import prepare_work, ANALYZER_VERSION
from test_service import docx, seed
from test_feasting_integration import package


MAIN = {'id': 'work_test', 'title': 'Feasting on the Word: Year A, Volume 4', 'profile': {}}
PROSE = 'A complete reflection explores this scriptural reading in its literary and pastoral contexts with sustained attention. '


def file_record(name='one', **extra):
    return {'id': 'file_' + name, 'sha256': 'sha_' + name, 'path': '/test/' + name + '.docx',
            'available': True, 'state': 'ready', **extra}


def blocks(items):
    result = []
    for i, item in enumerate(items):
        if isinstance(item, tuple):
            level, text = item
        else:
            level, text = None, item
        result.append({'ordinal': i, 'kind': 'heading' if level else 'paragraph', 'text': text,
                       'level': level, 'heading_path': [text] if level else [],
                       'locator': {'member': 'word/document.xml', 'paragraph': i + 1},
                       'is_boilerplate': False, 'links': [], 'bookmarks': []})
    return result


def prepare(tmp_path, items, work=MAIN, files=None):
    files = files or [file_record()]
    extraction = {f['id']: {'blocks': b, 'metadata': {}, 'warnings': [], 'images': []}
                  for f, b in zip(files, items) if b is not None}
    report = prepare_work(SimpleNamespace(state=tmp_path), work, files, extraction)
    return report, extraction


def test_feasting_semantic_parents_missing_slot_and_running_label(tmp_path):
    source = blocks([
        (1, 'PROPER 17'), (1, 'Psalm 26:1–8'), (1, 'Theological Perspective'),
        PROSE, 'ALPHA WRITER', (2, 'Pastoral Perspective'), PROSE,
        'Pastoral Perspective', PROSE, 'BETA WRITER', (1, 'Exegetical Perspective'),
        PROSE, 'GAMMA WRITER', 'Homiletical Perspective', PROSE, 'DELTA WRITER',
        (1, 'Contributors'), 'Alpha Writer, Professor of Theology',
        'Beta Writer, Professor of Ministry', 'Gamma Writer, Professor of Exegesis',
        'Delta Writer, Professor of Preaching'])
    original = deepcopy(source)
    report, e = prepare(tmp_path, [source])
    assert report['state'] == 'supported'
    assert report['recovered_headings'] == 1
    assert source[7]['kind'] == 'paragraph'
    assert source[13]['kind'] == 'heading'
    assert source[1]['heading_path'] == ['PROPER 17', 'Psalm 26:1–8']
    for i in [2, 5, 10, 13]:
        assert source[i]['structure_parent_key'] == 'file_one:1'
        assert source[i]['level'] == 3
        assert source[i]['heading_path'][:2] == ['PROPER 17', 'Psalm 26:1–8']
    assert source[13]['source_kind'] == 'paragraph'
    assert source[13]['source_level'] is None
    assert [(b['text'], b['ordinal'], b['locator']) for b in source] == [(b['text'], b['ordinal'], b['locator']) for b in original]
    cached, copied = prepare(tmp_path, [deepcopy(original)])
    assert cached['cache_reused']
    assert copied['file_one']['blocks'] == source


def test_seams_carry_actual_parent_identity_but_gaps_interrupt_it(tmp_path):
    first = blocks([(1, 'PROPER 27'), (1, 'Matthew 25:1–13'), (2, 'Theological Perspective'), PROSE])
    second = blocks([(3, 'Pastoral Perspective'), PROSE])
    f1, f2, gap = file_record(), file_record('two'), file_record('gap', available=False, state='missing')
    _, normal = prepare(tmp_path / 'healthy', [deepcopy(first), deepcopy(second)], files=[f1, f2])
    assert normal[f2['id']]['blocks'][0]['structure_parent_key'] == 'file_one:1'
    assert normal[f2['id']]['blocks'][0]['heading_path'] == ['PROPER 27', 'Matthew 25:1–13', 'Pastoral Perspective']
    report, broken = prepare(tmp_path / 'gap', [first, None, second], files=[f1, gap, f2])
    assert broken[f2['id']]['blocks'][0]['structure_parent_key'] is None
    assert any(i['code'] == 'unresolved_parent' for i in report['issues'])


def test_companions_do_not_acquire_main_series_four_perspective_rules(tmp_path):
    source = blocks([(1, 'Advent'), (2, 'Pastoral Perspective'), PROSE])
    report, _ = prepare(tmp_path, [source], work={'title': 'Feasting on the Word Advent Companion'})
    assert not any(i['code'] in {'perspective_coverage', 'unresolved_parent'} for i in report['issues'])
    assert source[1]['structure_role'] == 'section'


def test_source_label_variants_are_semantic_metadata_not_rewritten_text(tmp_path):
    source = blocks([(1, 'PROPER 17 Psalm 26:1–8'), (1, 'Homiletiacal Perspective'), PROSE])
    _, _ = prepare(tmp_path, [source])
    assert source[0]['structure_groups'][0]['title'] == 'PROPER 17'
    assert source[1]['text'] == 'Homiletiacal Perspective'
    assert source[1]['perspective_kind'] == 'Homiletical Perspective'
    assert source[1]['structure_parent_key'] == 'file_one:0'


@pytest.mark.parametrize('reading', ['Wisdom of Solomon 10:15–21', 'Psalm 6y', 'John 11(1–9) 10–18',
                                    '1 Corinthians n:12–31a', 'Philemon 1-21', 'Psalms 42 and 43'])
def test_source_supported_scripture_heading_variants_keep_original_label(tmp_path, reading):
    source = blocks([(1, 'PROPER 17'), (1, reading), (1, 'Theological Perspective'), PROSE])
    prepare(tmp_path, [source])
    assert source[1]['text'] == reading
    assert source[1]['structure_role'] == 'scripture_reading'
    assert source[2]['structure_parent_key'] == 'file_one:1'


def test_native_subheadings_belong_to_complete_chapter_not_separate_chunks(tmp_path):
    root = tmp_path / 'books'
    path = docx(root / 'Author' / 'book.docx', [
        ('Heading1', 'Chapter One'), PROSE, ('Heading2', 'First argument'), PROSE,
        ('Heading2', 'Second argument'), PROSE, ('Heading1', 'Chapter Two'), 'Next chapter.'])
    lib = seed(root, [{'title': 'A Monograph', 'paths': [path]}])
    with lib._db() as db:
        units = [dict(r) for r in db.execute('SELECT * FROM reading_units ORDER BY ordinal')]
        assert [u['title'] for u in units] == ['Chapter One', 'Chapter Two']
        sub = db.execute('SELECT * FROM outline_nodes WHERE title=?', ('First argument',)).fetchone()
        chapter = db.execute('SELECT * FROM outline_nodes WHERE title=?', ('Chapter One',)).fetchone()
        assert sub['parent_id'] == chapter['id']
        assert sub['unit_id'] == chapter['unit_id']
        texts = [r[0] for r in db.execute('SELECT b.text FROM unit_blocks u JOIN blocks b ON b.id=u.block_id WHERE u.unit_id=? ORDER BY u.ordinal', (units[0]['id'],))]
    assert 'First argument' in texts and 'Second argument' in texts
    assert 'Next chapter.' not in texts
    original_ids = [u['id'] for u in units]
    lib.sync(rebuild=True, semantic=False)
    with lib._db() as db:
        assert [r[0] for r in db.execute('SELECT id FROM reading_units ORDER BY ordinal')] == original_ids


def test_owned_notes_do_not_capture_intervening_essay(tmp_path):
    root = tmp_path / 'books'
    path = package(root)
    lib = seed(root, [{'title': 'Feasting on the Word: Year A, Volume 1', 'paths': [path],
                       'metadata': {'editors': ['Volume Editors']}}])
    with lib._db() as db:
        unit = db.execute('SELECT id FROM reading_units WHERE title=?', ('Theological Perspective',)).fetchone()[0]
        rows = db.execute('SELECT b.text,u.role FROM unit_blocks u JOIN blocks b ON b.id=u.block_id WHERE unit_id=? ORDER BY u.ordinal', (unit,)).fetchall()
    text = '\n'.join(r[0] for r in rows)
    assert 'Turquoise theological note' in text
    assert 'Copper homiletics' not in text
    assert 'Magenta shared note' not in text
    assert any('Turquoise' in r[0] and r[1] == 'note' for r in rows)


def test_sparse_books_are_readable_but_not_certified_complete_units(tmp_path):
    root = tmp_path / 'books'
    path = docx(root / 'Author' / 'book.docx', [('Heading1', 'Contents'), PROSE * 220])
    lib = seed(root, [{'title': 'Flattened Book', 'paths': [path]}])
    work = lib.book(lib.books()[0]['id'])
    assert work['structure']['state'] == 'needs_review'
    with lib._db() as db:
        units = [json.loads(r[0]) for r in db.execute('SELECT data FROM reading_units')]
    assert units and all(u['structure_status'] == 'needs_review' for u in units)
    assert any(i['code'] == 'sparse_outline' for i in units[0]['structure_issues'])


def test_number_and_title_are_one_outline_label_without_source_loss(tmp_path):
    root = tmp_path / 'books'
    path = docx(root / 'Author' / 'book.docx', [('Heading1', 'Book One'), ('Heading1', 'Foundations'),
                                              ('Heading2', '1'), ('Heading2', 'The First Question'), PROSE])
    lib = seed(root, [{'title': 'Numbered Chapters', 'paths': [path]}])
    with lib._db() as db:
        assert [r[0] for r in db.execute('SELECT title FROM outline_nodes ORDER BY ordinal')] == ['Book One: Foundations', '1: The First Question']
        assert [r[0] for r in db.execute('SELECT text FROM blocks ORDER BY ordinal')] == ['Book One', 'Foundations', '1', 'The First Question', PROSE]


def test_nested_epub_navigation_recovers_unstyled_headings_for_future_imports(tmp_path):
    path = tmp_path / 'source.epub'
    with ZipFile(path, 'w') as z:
        z.writestr('mimetype', 'application/epub+zip')
        z.writestr('META-INF/container.xml', '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="EPUB/package.opf"/></rootfiles></container>')
        z.writestr('EPUB/package.opf', '<package xmlns="http://www.idpf.org/2007/opf" version="3.0"><manifest><item id="body" href="body.xhtml" media-type="application/xhtml+xml"/><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/></manifest><spine><itemref idref="body"/></spine></package>')
        z.writestr('EPUB/body.xhtml', '<html xmlns="http://www.w3.org/1999/xhtml"><body><p id="chapter">Chapter One</p><p>Opening text.</p><p id="sub">A Smaller Question</p><p>Substantial discussion.</p><p>CAPITALS WITHOUT EVIDENCE</p></body></html>')
        z.writestr('EPUB/nav.xhtml', '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><body><nav epub:type="toc"><ol><li><a href="body.xhtml#chapter">Chapter One</a><ol><li><a href="body.xhtml#sub">A Smaller Question</a></li></ol></li></ol></nav></body></html>')
    extraction = extract_file(path)
    original = deepcopy(extraction['blocks'])
    f = file_record(path=str(path))
    report = prepare_work(SimpleNamespace(state=tmp_path / 'state'), {'title': 'A New Import'}, [f], {f['id']: extraction})
    chapter = next(b for b in extraction['blocks'] if b['text'] == 'Chapter One' and not b.get('is_navigation'))
    sub = next(b for b in extraction['blocks'] if b['text'] == 'A Smaller Question' and not b.get('is_navigation'))
    assert chapter['kind'] == sub['kind'] == 'heading'
    assert sub['heading_path'] == ['Chapter One', 'A Smaller Question']
    assert sub['structure_parent_key'] == f"{f['id']}:{chapter['ordinal']}"
    assert next(b for b in extraction['blocks'] if b['text'] == 'CAPITALS WITHOUT EVIDENCE')['kind'] == 'paragraph'
    assert [(b['text'], b['locator']) for b in extraction['blocks']] == [(b['text'], b['locator']) for b in original]


def test_provisional_bibliographic_author_does_not_get_verified_badge(tmp_path):
    root = tmp_path / 'books'
    path = docx(root / 'Author' / 'book.docx', [('Heading1', 'An Essay'), PROSE])
    lib = seed(root, [{'title': 'Anthology', 'paths': [path]}])
    section = next(s for s in lib.book(lib.books()[0]['id'])['sections'] if s['title'] == 'An Essay')
    lib.annotate(section['id'], {'field': 'bibliography', 'value': {'type': 'chapter', 'title': 'Confirmed Essay Title'},
                                 'status': 'confirmed', 'origin': 'user', 'evidence': 'Reviewed title only.'})
    lib.annotate(section['id'], {'field': 'bibliography', 'value': {'authors': [{'literal': 'Possible Writer'}]},
                                 'status': 'provisional', 'origin': 'codex', 'evidence': 'Candidate identity only.'})
    lib.sync(semantic=False)
    with lib._db() as db:
        node = json.loads(db.execute('SELECT data FROM outline_nodes WHERE id=?', (section['id'],)).fetchone()[0])
    assert node['attribution_verified'] is False


def test_confirmed_scoped_attribution_independently_verifies_outline_credit(tmp_path):
    root = tmp_path / 'books'
    path = docx(root / 'Editor' / 'book.docx', [('Heading1', 'An Essay'), PROSE])
    lib = seed(root, [{'title': 'An Edited Book', 'metadata': {'editors': ['Volume Editor']}, 'paths': [path]}])
    section = next(s for s in lib.book(lib.books()[0]['id'])['sections'] if s['title'] == 'An Essay')
    lib.annotate(section['id'], {'field': 'attribution', 'value': 'Reviewed Contributor', 'status': 'confirmed',
                                 'origin': 'user', 'evidence': 'Verified closing byline for this essay.'})
    lib.sync(semantic=False)
    with lib._db() as db:
        node = json.loads(db.execute('SELECT data FROM outline_nodes WHERE id=?', (section['id'],)).fetchone()[0])
    assert node['attribution'] == 'Reviewed Contributor'
    assert node['attribution_verified'] is True


def test_heading_only_internal_group_keeps_complete_chapter_membership(tmp_path):
    root = tmp_path / 'books'
    paragraphs = [('Heading1', 'Chapter One'), 'Chapter introduction.',
                  ('Heading2', 'An Internal Group'), ('Heading3', 'First subtopic'), 'First discussion.',
                  ('Heading3', 'Second subtopic'), 'Second discussion.', ('Heading1', 'Chapter Two'), 'Later text.']
    path = docx(root / 'Author' / 'book.docx', paragraphs)
    lib = seed(root, [{'title': 'Chapter With Internal Groups', 'paths': [path]}])
    with lib._db() as db:
        units = list(db.execute('SELECT id,title FROM reading_units ORDER BY ordinal'))
        assert [u['title'] for u in units] == ['Chapter One', 'Chapter Two']
        texts = [r[0] for r in db.execute('SELECT b.text FROM unit_blocks u JOIN blocks b ON b.id=u.block_id WHERE u.unit_id=? ORDER BY u.ordinal', (units[0]['id'],))]
        assert texts == [p[1] if isinstance(p, tuple) else p for p in paragraphs[:7]]


def test_known_contribution_keeps_internal_subheading_in_edited_volume(tmp_path):
    root = tmp_path / 'books'
    path = docx(root / 'Editors' / 'book.docx', [('Heading1', 'PROPER 17'), ('Heading1', 'Matthew 25:1–13'),
        ('Heading2', 'Theological Perspective'), 'Contribution introduction.',
        ('Heading4', 'The inner argument'), 'Its complete discussion.',
        ('Heading2', 'Pastoral Perspective'), 'Separate contribution.'])
    lib = seed(root, [{'title': MAIN['title'], 'author': 'Volume Editors', 'metadata': {'editors': ['Volume Editors']}, 'paths': [path]}])
    with lib._db() as db:
        unit = db.execute('SELECT id FROM reading_units WHERE title=?', ('Theological Perspective',)).fetchone()[0]
        texts = [r[0] for r in db.execute('SELECT b.text FROM unit_blocks u JOIN blocks b ON b.id=u.block_id WHERE u.unit_id=? ORDER BY u.ordinal', (unit,))]
        assert texts == ['Theological Perspective', 'Contribution introduction.', 'The inner argument', 'Its complete discussion.']
        assert not db.execute('SELECT id FROM reading_units WHERE title=?', ('The inner argument',)).fetchone()


def test_source_gap_marks_both_incomplete_prefix_and_continuation_units(tmp_path):
    root = tmp_path / 'books'
    first = docx(root / 'Author' / '01.docx', [('Heading1', 'Chapter One'), 'Opening source text.'])
    middle = docx(first.parent / '02.docx', ['Middle source text.'])
    last = docx(first.parent / '03.docx', ['Continued source text.', ('Heading1', 'Chapter Two'), 'Independent chapter.'])
    lib = seed(root, [{'title': 'Split Chapter Gap', 'paths': [first, middle, last]}])
    middle.unlink()
    lib.sync(semantic=False)
    with lib._db() as db:
        units = {r['title']: json.loads(r['data']) for r in db.execute('SELECT title,data FROM reading_units')}
    assert units['Chapter One']['structure_status'] == 'needs_review'
    assert units['Continuation after unavailable source part']['structure_status'] == 'needs_review'
    assert units['Chapter Two']['structure_status'] == 'supported'


def test_numeric_heading_style_gaps_are_not_missing_ancestry(tmp_path):
    source = blocks([(2, 'Chapter One'), PROSE, (4, 'Nested argument'), PROSE])
    report, _ = prepare(tmp_path, [source], work={'title': 'Sparse Numeric Styles'})
    assert report['state'] == 'supported'
    assert source[2]['structure_parent_key'] == 'file_one:0'
    source = blocks([(1, 'Chapter One'), (2, 'Known level'), PROSE, (1, 'Chapter Two'), (3, 'Missing intermediate parent'), PROSE])
    report, _ = prepare(tmp_path / 'missing', [source], work={'title': 'Actual Missing Ancestry'})
    assert [i['source']['ordinal'] for i in report['issues'] if i['code'] == 'skipped_heading_level'] == [4]


def test_epub_inline_and_container_anchors_recover_split_navigation_labels(tmp_path):
    path = tmp_path / 'source.epub'
    with ZipFile(path, 'w') as z:
        z.writestr('mimetype', 'application/epub+zip')
        z.writestr('META-INF/container.xml', '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="EPUB/package.opf"/></rootfiles></container>')
        z.writestr('EPUB/package.opf', '<package xmlns="http://www.idpf.org/2007/opf" version="3.0"><manifest><item id="body" href="body.xhtml" media-type="application/xhtml+xml"/><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/></manifest><spine><itemref idref="body"/></spine></package>')
        z.writestr('EPUB/body.xhtml', '<html xmlns="http://www.w3.org/1999/xhtml"><body><section id="part"><p>PART</p><p>ONE</p><p>A New World</p><p><a id="chapter">A Poem</a></p><p>A Writer</p><p>First line.<br/>Second line.</p><p><a id="wrong">Unrelated text</a></p></section></body></html>')
        z.writestr('EPUB/nav.xhtml', '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><body><nav epub:type="toc"><ol><li><a href="body.xhtml#part">Part One: A New World</a><ol><li><a href="body.xhtml#chapter">A Poem A Writer</a></li><li><a href="body.xhtml#wrong">Different label</a></li></ol></li></ol></nav></body></html>')
    extraction = extract_file(path)
    original = deepcopy(extraction['blocks'])
    f = file_record(path=str(path))
    report = prepare_work(SimpleNamespace(state=tmp_path / 'state'), {'title': 'Fresh Split Labels'}, [f], {f['id']: extraction})
    hs = [b for b in extraction['blocks'] if b['kind'] == 'heading']
    assert [b['structure_title'] for b in hs] == ['Part One: A New World', 'A Poem A Writer']
    assert hs[1]['structure_parent_key'] == f"{f['id']}:{hs[0]['ordinal']}"
    assert next(b for b in extraction['blocks'] if b['text'] == 'Unrelated text')['kind'] == 'paragraph'
    assert [(b['text'], b['locator']) for b in extraction['blocks']] == [(b['text'], b['locator']) for b in original]


@pytest.mark.parametrize('target_pages,expected', [(['12'], 1), (['13'], 0), (['12', '12'], 0)])
def test_printed_contents_recovery_requires_unique_title_and_matching_page(tmp_path, target_pages, expected):
    source = blocks(['CONTENTS', 'A Small Discovery 12', 'Unrelated title 18'])
    for page in target_pages:
        source.extend(blocks(['A Small Discovery', PROSE]))
        source[-2]['locator']['page'] = page
        source[-1]['locator']['page'] = page
    for i, b in enumerate(source):
        b['ordinal'] = i
        b['locator']['paragraph'] = i + 1
    report, _ = prepare(tmp_path, [source], work={'title': 'Printed Contents Example'})
    recovered = [b for b in source if b['kind'] == 'heading']
    assert len(recovered) == expected
    if recovered:
        assert recovered[0]['heading_evidence']['origin'] == 'printed_contents_title_and_page'
        assert report['boundary_samples'][0]['heading']['locator']['page'] == '12'
    assert report['contents_evidence'][0]['label'] == 'CONTENTS'
