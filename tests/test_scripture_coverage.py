"""Explicit Scripture coverage must work beyond the Gospels without guessing."""
import pytest

from book_library.service import Library
from test_service import annotate, docx, seed


@pytest.mark.parametrize('reference', ['Genesis 1', 'Romans 8', '1 John 1', 'Psalm 23', 'Wisdom 7:22–30'])
def test_scripture_filter_honors_explicit_non_gospel_coverage(tmp_path, reference):
    root = tmp_path / 'books'
    source = docx(root / 'Commentary' / 'Book.docx', ['Copper witness in this commentary.'])
    lib = seed(root, [{'title': 'Commentary', 'paths': [source]}])
    work_id = lib.books()[0]['id']
    annotate(lib, work_id, [reference], field='coverage')
    lib.sync(semantic=False)

    result = lib.search('copper witness', filters={'scripture': reference}, engine='exact')
    assert [hit['work_id'] for hit in result['direct']] == [work_id]
    assert result['coverage']['eligible_books'] == 1


def test_explicit_coverage_uses_whole_labels_without_expanding_ranges(tmp_path):
    lib = Library(tmp_path)
    work = {'title': 'Commentary', 'coverage': ['Genesis 11', 'Romans 8:1–11']}
    assert lib._covers(work, '  ROMANS   8:1-11  ')
    assert not lib._covers(work, 'Genesis 1')
    assert not lib._covers(work, 'Romans 8')
    assert not lib._covers(work, 'Romans 8:1')
    assert not lib._covers(work, 'Romans 8:1–12')
    assert lib._covers({'title': 'Commentary', 'coverage': {'Genesis 1': 'Verified chapter'}}, 'Genesis 1')
    assert not lib._covers({'title': 'Unknown coverage'}, 'Genesis 1')
    assert lib._covers({'title': 'Unknown coverage'}, 'Genesis 1', unknown_ok=True)


def test_verified_feasting_range_takes_precedence_over_conflicting_coverage(tmp_path):
    lib = Library(tmp_path)
    work = {'title': 'Feasting on the Gospels: Luke, Volume 2, Chapters 12–24',
            'coverage': ['Luke 1', 'Romans 8']}
    assert lib._covers(work, 'Luke 12')
    assert lib._covers(work, 'Luke 24:1–12')
    assert lib._covers(work, 'Luke 12–24')
    assert not lib._covers(work, 'Luke 1')
    assert not lib._covers(work, 'Luke 24–25')
    assert not lib._covers(work, 'Romans 8')
    assert not lib._covers({'title': 'Feasting on the Gospels: John, Volume 1, Chapters 1–9'}, '1 John 1')
