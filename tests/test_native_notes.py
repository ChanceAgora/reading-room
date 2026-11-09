"""Source-reference membership is independent of physical note placement."""
from zipfile import ZipFile

from book_library.native_notes import analyze_native_notes
from test_service import docx, seed, W


def note_book(tmp_path, *, shared=False):
    root = tmp_path / 'books'
    path = docx(root / 'Book' / 'book.docx', [
        ('Heading1', 'First chapter'), 'First body',
        ('Heading1', 'Second chapter'), 'Second body',
    ])
    with ZipFile(path) as source:
        parts = {n: source.read(n) for n in source.namelist()}
    body = parts['word/document.xml'].decode().replace('First body</w:t>', 'First body</w:t><w:footnoteReference w:id="2"/>')
    if shared:
        body = body.replace('Second body</w:t>', 'Second body</w:t><w:footnoteReference w:id="2"/>')
    parts['word/document.xml'] = body
    parts['word/footnotes.xml'] = f'<w:footnotes xmlns:w="{W}"><w:footnote w:id="2"><w:p><w:r><w:t>Owned note opening.</w:t></w:r></w:p><w:p><w:r><w:t>Owned note continuation.</w:t></w:r></w:p></w:footnote><w:footnote w:id="3"><w:p><w:r><w:t>Unreferenced note.</w:t></w:r></w:p></w:footnote></w:footnotes>'
    with ZipFile(path, 'w') as output:
        for name, contents in parts.items():
            output.writestr(name, contents)
    return seed(root, [{'title': 'Native footnotes', 'author': 'Test Author', 'paths': [path]}])


def readings(lib):
    with lib._db() as db:
        return {row['title']: lib.read_unit(row['id']) for row in db.execute('SELECT id,title FROM reading_units ORDER BY ordinal')}


def test_native_word_notes_follow_reference_not_last_chapter(tmp_path):
    lib = note_book(tmp_path)
    units = readings(lib)
    first = units['First chapter']['blocks']
    second = units['Second chapter']['blocks']
    unassigned = units['Source notes — contributor unresolved']['blocks']
    assert [b['text'] for b in first if b['role'] == 'note'] == ['Owned note opening.', 'Owned note continuation.']
    assert not any(b['role'] == 'note' for b in second)
    assert [b['text'] for b in unassigned] == ['Unreferenced note.']
    reference = next(b for b in first if b['text'] == 'First body')
    note = next(b for b in first if b['text'] == 'Owned note opening.')
    assert reference['note_links'][0]['target_block_id'] == note['id']
    assert note['backlinks'] == [reference['id']]


def test_shared_native_note_stays_unassigned(tmp_path):
    units = readings(note_book(tmp_path, shared=True))
    assert not any(b['role'] == 'note' for title in ['First chapter', 'Second chapter'] for b in units[title]['blocks'])
    assert len(units['Source notes — contributor unresolved']['blocks']) == 3


def test_equal_note_ids_in_different_members_do_not_collide():
    file = {'id': 'f', 'sha256': 'sha', 'available': True, 'state': 'ready'}
    blocks = [
        {'ordinal': 0, 'kind': 'heading', 'text': 'Chapter', 'locator': {'member': 'body'}},
        {'ordinal': 1, 'kind': 'paragraph', 'text': 'Body', 'locator': {'member': 'body'},
         'note_refs': [{'target': {'member': 'footnotes', 'note_id': '2'}}]},
        {'ordinal': 2, 'kind': 'note', 'text': 'Footnote', 'locator': {'member': 'footnotes', 'note_id': '2'}},
        {'ordinal': 3, 'kind': 'note', 'text': 'Endnote', 'locator': {'member': 'endnotes', 'note_id': '2'}},
    ]
    result = analyze_native_notes({'id': 'w'}, [file], {'f': {'blocks': blocks}})
    assert result['f:2']['owner'] == 'f:0'
    assert result['f:3']['owner'] is None


def test_epub_supplemental_note_returns_to_referencing_chapter(tmp_path):
    from test_extract import ExtractTests
    from book_library.service import Library
    root = tmp_path / 'books'; root.mkdir()
    fixture = ExtractTests(); fixture.root = root
    fixture.epub({
        'first.xhtml': '<h1 id="first">First chapter</h1><p id="reference">First body<a epub:type="noteref" href="notes.xhtml#n1">1</a>.</p>',
        'second.xhtml': '<h1>Second chapter</h1><p>Other prose.</p>',
        'notes.xhtml': '<aside epub:type="footnote" id="n1"><p>Owned EPUB note.</p><p>Second note paragraph.</p></aside><aside epub:type="footnote" id="n2"><p>Unreferenced EPUB note.</p></aside>',
    }, ['first.xhtml', 'second.xhtml'])
    lib = Library(root); lib.sync(semantic=False)
    units = readings(lib)
    assert [b['text'] for b in units['First chapter']['blocks'] if b['role'] == 'note'] == ['Owned EPUB note.', 'Second note paragraph.']
    assert not any(b['role'] == 'note' for b in units['Second chapter']['blocks'])
    assert [b['text'] for b in units['Source notes — contributor unresolved']['blocks']] == ['Unreferenced EPUB note.']
    first = units['First chapter']['blocks']
    reference = next(b for b in first if b['text'].startswith('First body'))
    note = next(b for b in first if b['text'] == 'Owned EPUB note.')
    assert reference['note_links'][0]['target_block_id'] == note['id']
    assert note['backlinks'] == [reference['id']]


def test_gap_blocks_native_note_owner_continuity():
    files = [{'id': 'one', 'available': True, 'state': 'ready'},
             {'id': 'gap', 'available': False, 'state': 'missing'},
             {'id': 'two', 'available': True, 'state': 'ready'}]
    extractions = {
        'one': {'blocks': [{'ordinal': 0, 'kind': 'heading', 'text': 'Before gap', 'locator': {'member': 'body'}}]},
        'two': {'blocks': [
            {'ordinal': 0, 'kind': 'paragraph', 'text': 'After gap', 'locator': {'member': 'body'},
             'note_refs': [{'target': {'member': 'footnotes', 'note_id': '2'}}]},
            {'ordinal': 1, 'kind': 'note', 'text': 'Note', 'locator': {'member': 'footnotes', 'note_id': '2'}},
        ]},
    }
    result = analyze_native_notes({'id': 'w'}, files, extractions)
    assert result['two:1']['owner'] is None
    assert 'gap' in result['two:1']['reason']
