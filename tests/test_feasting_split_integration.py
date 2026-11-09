"""Source continuity across Word parts, including unavailable intermediate parts."""
from zipfile import ZipFile

import pytest

from test_feasting_integration import hit
from test_service import W, docx, seed


PROSE = 'This essay considers the Beatitudes in their surrounding Gospel context and develops a substantial interpretation for teaching.'


def add_native_note(path):
    """An ordinary extracted Word footnote appears at the end of its part."""
    with ZipFile(path) as z:
        members = {name: z.read(name) for name in z.namelist()}
    members['word/footnotes.xml'] = (f'<w:footnotes xmlns:w="{W}"><w:footnote w:id="1">'
        '<w:p><w:r><w:t>Violet source footnote with no reciprocal bookmark mapping.</w:t></w:r></w:p>'
        '</w:footnote></w:footnotes>').encode()
    with ZipFile(path, 'w') as z:
        for name, value in members.items():
            z.writestr(name, value)


def test_split_essay_restores_owner_after_native_note_and_preserves_identity(tmp_path):
    root = tmp_path / 'books'
    first = docx(root / 'Commentary' / '001.docx', [
        ('Heading1', 'Matthew 5:1–12'), ('Heading2', 'Theological Perspective'), 'Amber opening. ' + PROSE])
    add_native_note(first)
    second = docx(first.parent / '002.docx', [
        'Copper continuation. ' + PROSE, 'MARCIA Y. RIGGS',
        ('Heading1', 'Contributors'), 'Marcia Y. Riggs, Professor of Ethics, A Seminary'])
    lib = seed(root, [{'title': 'Feasting on the Word: Test Volume', 'author': 'Volume Editors',
                       'paths': [first, second], 'metadata': {'editors': ['Volume Editors']}}])
    opening = hit(lib, 'amber opening'); continuation = hit(lib, 'copper continuation')
    assert opening['section_id'] == continuation['section_id']
    assert opening['attribution'] == continuation['attribution'] == 'Marcia Y. Riggs'
    note = hit(lib, 'violet source footnote')
    assert note['section_id'] != opening['section_id']
    assert 'unverified' in note['attribution'].lower()
    reading = lib.read(continuation['id'], context=1)
    assert [b['global_ordinal'] for b in reading['blocks']] == sorted(b['global_ordinal'] for b in reading['blocks'])
    assert next(b for b in reading['blocks'] if 'Copper continuation' in b['text'])['attribution'] == 'Marcia Y. Riggs'
    assert lib.cite(continuation['id'])['full_note'].startswith('Marcia Y. Riggs, “Theological Perspective,”')
    lib.sync(rebuild=True, semantic=False)
    assert hit(lib, 'copper continuation')['section_id'] == opening['section_id']


def test_missing_intermediate_part_does_not_reattribute_remaining_essay(tmp_path):
    root = tmp_path / 'books'
    first = docx(root / 'Commentary' / '001.docx', [
        ('Heading1', 'Matthew 5:1–12'), ('Heading2', 'Theological Perspective'), 'Amber opening. ' + PROSE])
    second = docx(first.parent / '002.docx', ['MARCIA Y. RIGGS',
        ('Heading2', 'Homiletical Perspective'), 'Copper homiletical. ' + PROSE])
    third = docx(first.parent / '003.docx', ['RONALD J. ALLEN', ('Heading1', 'Contributors'),
        'Marcia Y. Riggs, Professor of Ethics, A Seminary', 'Ronald J. Allen, Professor of Preaching, A Seminary'])
    lib = seed(root, [{'title': 'Feasting on the Word: Test Volume', 'author': 'Volume Editors',
                       'paths': [first, second, third], 'metadata': {'editors': ['Volume Editors']}}])
    assert hit(lib, 'amber opening')['attribution'] == 'Marcia Y. Riggs'
    assert hit(lib, 'copper homiletical')['attribution'] == 'Ronald J. Allen'
    second.unlink()
    lib.sync(semantic=False)
    remaining = hit(lib, 'amber opening')
    assert 'unverified' in remaining['attribution'].lower()
    assert remaining['attribution'] != 'Ronald J. Allen'
    assert not lib.search('copper homiletical', engine='exact', connections=0)['direct']
    assert 'section.authorship' in lib.cite(remaining['id'])['review_fields']


def test_failed_part_does_not_join_separate_contributors(tmp_path):
    root = tmp_path / 'books'
    first = docx(root / 'Commentary' / '001.docx', [
        ('Heading1', 'Matthew 5:1–12'), ('Heading2', 'Theological Perspective'), 'Amber opening. ' + PROSE])
    broken = first.parent / '002.docx'; broken.write_bytes(b'Not a Word package')
    third = docx(first.parent / '003.docx', ['RONALD J. ALLEN', ('Heading1', 'Contributors'),
        'Ronald J. Allen, Professor of Preaching, A Seminary'])
    lib = seed(root, [{'title': 'Feasting on the Word: Test Volume', 'author': 'Volume Editors',
                       'paths': [first, broken, third], 'metadata': {'editors': ['Volume Editors']}}])
    assert lib.status()['failures']
    assert 'unverified' in hit(lib, 'amber opening')['attribution'].lower()


@pytest.mark.parametrize('gap_mode', ['missing', 'empty', 'failed', 'notice_only'])
def test_missing_heading_part_cannot_extend_previous_verified_essay(tmp_path, gap_mode):
    root = tmp_path / 'books'
    first = docx(root / 'Commentary' / '001.docx', [
        ('Heading1', 'Matthew 5:1–12'), ('Heading2', 'Theological Perspective'),
        'Amber opening. ' + PROSE, 'MARCIA Y. RIGGS'])
    second = docx(first.parent / '002.docx', [
        ('Heading2', 'Homiletical Perspective'), 'Copper homiletical. ' + PROSE])
    third = docx(first.parent / '003.docx', ['Turquoise continuation. ' + PROSE, 'RONALD J. ALLEN',
        ('Heading1', 'Contributors'), 'Marcia Y. Riggs, Professor of Ethics, A Seminary',
        'Ronald J. Allen, Professor of Preaching, A Seminary'])
    lib = seed(root, [{'title': 'Feasting on the Word: Test Volume', 'author': 'Volume Editors',
                       'paths': [first, second, third], 'metadata': {'editors': ['Volume Editors']}}])
    original = hit(lib, 'amber opening')
    assert original['attribution'] == 'Marcia Y. Riggs'
    assert hit(lib, 'turquoise continuation')['attribution'] == 'Ronald J. Allen'
    if gap_mode == 'missing':
        second.unlink()
    elif gap_mode == 'empty':
        docx(second, [])
    elif gap_mode == 'failed':
        second.write_bytes(b'Not a Word package')
    else:
        docx(second, ['NOTICE', 'This is a Bookshare download notice.', 'Begin Content'])
    lib.sync(semantic=False)
    remaining = hit(lib, 'turquoise continuation')
    assert 'unverified' in remaining['attribution'].lower()
    assert remaining['section_id'] != original['section_id']
    assert hit(lib, 'amber opening')['section_id'] == original['section_id']
    assert hit(lib, 'amber opening')['attribution'] == 'Marcia Y. Riggs'
