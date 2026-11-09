from copy import deepcopy

import pytest

from book_library.feasting import analyze_feasting, block_key


WORK = {'title': 'Feasting on the Word: Year A, Volume 1'}
F1 = {'id': 'file_a', 'path': '/books/part1.docx', 'sha256': 'hash1'}
F2 = {'id': 'file_b', 'path': '/books/part2.docx', 'sha256': 'hash2'}
PROSE = 'This is substantive essay text about the Beatitudes and their meaning within the surrounding Gospel narrative. '


def block(ordinal, text, kind='paragraph', path=None, **extra):
    return {'ordinal': ordinal, 'text': text, 'kind': kind,
            'heading_path': path or ['Matthew 5:1–12', 'Theological Perspective'],
            'locator': {'member': 'word/document.xml', 'paragraph': ordinal + 1}, **extra}


def heading(ordinal, name='Theological Perspective'):
    return block(ordinal, name, 'heading', ['Matthew 5:1–12', name])


def roster(ordinal, name='Marcia Y. Riggs'):
    return block(ordinal, name + ', Professor of Ethics, A Seminary', path=['Contributors'])


def link(label, bookmark, external=None):
    return {'label': label, 'target': {'bookmark': bookmark, **({'external_href': external} if external else {'member': 'word/document.xml'})}}


def test_verified_closing_byline_preserves_roster_spelling_and_source_evidence():
    blocks = [heading(0), block(1, PROSE), block(2, 'MARCIA Y. RIGGS'),
              block(3, 'Contributors', 'heading', ['Contributors']), roster(4)]
    before = deepcopy(blocks)
    result = analyze_feasting(WORK, [(F1, blocks)])
    c = result['contributions']['file_a:0']
    assert c['author'] == 'Marcia Y. Riggs'
    assert c['source_bibliography']['value']['authors'] == [{'literal': 'Marcia Y. Riggs'}]
    assert c['bibliography']['title'] == 'Theological Perspective'
    assert c['bibliography']['locator']['value'] == 'Matthew 5:1–12 / Theological Perspective'
    assert c['evidence']['byline']['ordinal'] == 2
    assert c['evidence']['roster']['ordinal'] == 4
    assert result['owners']['file_a:1'] == 'file_a:0'
    assert blocks == before


def test_reciprocal_notes_are_mapped_to_actual_essay_not_preceding_homiletical_author():
    blocks = [heading(0), block(1, PROSE, bookmarks=['c1_fn1a'], links=[link('1', 'c1_fn1')]),
              block(2, 'MARCIA Y. RIGGS'), heading(3, 'Homiletical Perspective'),
              block(4, PROSE), block(5, 'RONALD J. ALLEN'),
              block(6, '1. An outside author and cited work.', bookmarks=['c1_fn1'], links=[link('1.', 'c1_fn1a')]),
              block(7, 'Contributors', 'heading', ['Contributors']), roster(8), roster(9, 'Ronald J. Allen')]
    result = analyze_feasting(WORK, [(F1, blocks)])
    assert result['notes']['file_a:6']['owner'] == 'file_a:0'
    assert result['owners']['file_a:6'] == 'file_a:0'
    assert result['owners']['file_a:5'] == 'file_a:3'
    assert 'file_a:1' not in result['notes']  # fn1a is a body reference, not a note.
    assert result['boundaries'] == ['file_a:6']


def test_cross_split_file_essay_and_backlink_keep_one_contribution():
    first = [heading(0), block(1, PROSE, bookmarks=['u978_epub-ftnp308t-1a'], links=[link('1', 'u978_epub-ftnp308t-1')])]
    second = [block(0, PROSE), block(1, 'MARCIA Y. RIGGS'),
              block(2, '1. A footnote.', bookmarks=['u978_epub-ftnp308t-1'], links=[link('1.', 'u978_epub-ftnp308t-1a', 'legacy-part1.docx')]),
              block(3, 'Contributors', 'heading', ['Contributors']), roster(4)]
    result = analyze_feasting(WORK, [(F1, first), (F2, second)])
    assert len(result['contributions']) == 1
    assert result['owners']['file_b:0'] == 'file_a:0'
    assert result['notes']['file_b:2']['owner'] == 'file_a:0'


@pytest.mark.parametrize('gap', [None, [], [block(0, '')], [block(0, 'Bookshare notice', is_boilerplate=True)]])
def test_source_gap_cannot_join_an_earlier_heading_to_a_later_byline(gap):
    first = [heading(0), block(1, PROSE)]
    third = [block(0, 'RONALD J. ALLEN'),
             block(1, 'Contributors', 'heading', ['Contributors']), roster(2, 'Ronald J. Allen')]
    result = analyze_feasting(WORK, [(F1, first), (F2, gap), ({'id': 'file_c'}, third)])
    assert result['stats']['perspectives'] == 1
    assert not result['contributions']
    assert not result['owners']


def test_source_gap_preserves_complete_essays_and_reciprocal_note_evidence():
    first = [heading(0), block(1, PROSE, bookmarks=['body1'], links=[link('1', 'note1')]),
             block(2, 'MARCIA Y. RIGGS')]
    third = [block(0, '1. Source note.', kind='note', bookmarks=['note1'], links=[link('1.', 'body1')]),
             block(1, 'Contributors', 'heading', ['Contributors']), roster(2)]
    result = analyze_feasting(WORK, [(F1, first), (F2, None), ({'id': 'file_c'}, third)])
    assert result['contributions']['file_a:0']['author'] == 'Marcia Y. Riggs'
    assert result['notes']['file_c:0']['owner'] == 'file_a:0'


def test_name_in_middle_or_two_candidates_are_not_promoted():
    base = [heading(0), block(1, PROSE), block(2, 'MARCIA Y. RIGGS')]
    for tail in ([block(3, PROSE)], [block(3, 'MARCIA Y. RIGGS')]):
        blocks = base + tail + [block(4, 'Contributors', 'heading', ['Contributors']), roster(5)]
        assert not analyze_feasting(WORK, [(F1, blocks)])['contributions']


def test_no_roster_match_means_unknown_and_generic_caps_are_not_names():
    for name in ('UNKNOWN PERSON', 'AMEN', 'THEOLOGY AND HOPE'):
        blocks = [heading(0), block(1, PROSE), block(2, name),
                  block(3, 'Contributors', 'heading', ['Contributors']), roster(4)]
        assert not analyze_feasting(WORK, [(F1, blocks)])['contributions']


def test_unresolved_or_ambiguous_notes_never_inherit_preceding_author():
    for ambiguous in (False, True):
        body = block(1, PROSE, bookmarks=['c1_fn1a'], links=[link('1', 'c1_fn1')])
        blocks = [heading(0), body, block(2, 'MARCIA Y. RIGGS'),
                  block(3, '1. A footnote.', bookmarks=['c1_fn1'], links=[link('1.', 'c1_fn1a' if ambiguous else 'missing')]),
                  block(4, 'Contributors', 'heading', ['Contributors']), roster(5)]
        if ambiguous:
            blocks.append(block(6, PROSE, bookmarks=['c1_fn1a']))
        result = analyze_feasting(WORK, [(F1, blocks)])
        assert len(result['contributions']) == 1
        assert result['notes']['file_a:3']['owner'] is None
        assert 'file_a:3' not in result['owners']


def test_note_like_citation_without_reciprocal_link_does_not_create_owner():
    blocks = [heading(0), block(1, PROSE, bookmarks=['c1_fn1a']), block(2, 'MARCIA Y. RIGGS'),
              block(3, '1. A footnote.', bookmarks=['c1_fn1'], links=[link('1.', 'c1_fn1a')]),
              block(4, 'Contributors', 'heading', ['Contributors']), roster(5)]
    result = analyze_feasting(WORK, [(F1, blocks)])
    assert result['notes']['file_a:3']['owner'] is None


def test_other_series_and_non_perspective_headings_are_out_of_scope():
    blocks = [heading(0), block(1, PROSE), block(2, 'MARCIA Y. RIGGS'),
              block(3, 'Contributors', 'heading', ['Contributors']), roster(4)]
    assert not analyze_feasting({'title': 'Another anthology'}, [(F1, blocks)])['contributions']
    blocks[0] = block(0, 'Introduction', 'heading', ['Introduction'])
    assert not analyze_feasting(WORK, [(F1, blocks)])['contributions']


def test_bare_perspective_heading_has_unverified_not_invented_locator():
    blocks = [block(0, 'Theological Perspective', 'heading', ['Theological Perspective']), block(1, PROSE), block(2, 'MARCIA Y. RIGGS'),
              block(3, 'Contributors', 'heading', ['Contributors']), roster(4)]
    result = analyze_feasting(WORK, [(F1, blocks)])
    assert not result['contributions']['file_a:0']['bibliography']['locator']['verified']
    assert block_key('file_a', 2) == 'file_a:2'


def test_reversed_fn_anchor_suffix_and_nts_variants_follow_reciprocal_links():
    for body_marker, note_marker in [('c1-ftnp1-1', 'c1-ftnp1-1a'), ('c1-s02_nts01', 'c1-s02-nts01')]:
        blocks = [heading(0), block(1, PROSE, bookmarks=[body_marker], links=[link('1', note_marker)]),
                  block(2, 'MARCIA Y. RIGGS'),
                  block(3, '1. A source note.', bookmarks=[note_marker], links=[link('1.', body_marker)]),
                  block(4, 'Contributors', 'heading', ['Contributors']), roster(5)]
        result = analyze_feasting(WORK, [(F1, blocks)])
        assert 'file_a:1' not in result['notes']
        assert result['notes']['file_a:3']['owner'] == 'file_a:0'


def test_linkless_numbered_notes_are_separate_and_unowned():
    blocks = [heading(0), block(1, PROSE), block(2, 'MARCIA Y. RIGGS'),
              block(3, '1. An author and a published work.'),
              block(4, 'Contributors', 'heading', ['Contributors']), roster(5)]
    result = analyze_feasting(WORK, [(F1, blocks)])
    assert len(result['contributions']) == 1
    assert result['notes']['file_a:3']['owner'] is None
    assert 'file_a:3' not in result['owners']


def test_numbered_prose_inside_essay_is_not_a_shared_note():
    blocks = [heading(0), block(1, '1. ' + PROSE, bookmarks=['c1_fn1'], links=[link('1', 'c1_fn1a')]),
              block(2, 'MARCIA Y. RIGGS'),
              block(3, '1. An actual source note.', bookmarks=['c1_fn1a'], links=[link('1.', 'c1_fn1')]),
              block(4, 'Contributors', 'heading', ['Contributors']), roster(5)]
    result = analyze_feasting(WORK, [(F1, blocks)])
    assert result['owners']['file_a:1'] == 'file_a:0'
    assert 'file_a:1' not in result['notes']
    assert result['notes']['file_a:3']['owner'] == 'file_a:0'


def test_attached_superscript_note_number_uses_numeric_source_backlink():
    blocks = [heading(0), block(1, PROSE, bookmarks=['c1-ftn1a'], links=[link('1', 'c1-ftn1')]),
              block(2, 'MARCIA Y. RIGGS'),
              block(3, '1A published work and its author.', bookmarks=['c1-ftn1'], links=[link('1', 'c1-ftn1a')]),
              block(4, 'Contributors', 'heading', ['Contributors']), roster(5)]
    result = analyze_feasting(WORK, [(F1, blocks)])
    assert result['notes']['file_a:3']['owner'] == 'file_a:0'
