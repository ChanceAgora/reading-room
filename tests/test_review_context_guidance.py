"""Guidance must describe the requested section, not its export wrapper."""
from pathlib import Path

import pytest

from book_library.passage_segments import TEXT_TYPES
from book_library.review_education import TEXT_TYPE_GUIDE, field_education
from test_service import docx, seed


@pytest.fixture
def guided_book(tmp_path):
    root = tmp_path / 'books'
    path = docx(root / 'Collection' / 'book.docx', [
        ('Heading1', 'Export information'),
        *[f'An export preface line {i}.' for i in range(40)],
        ('Heading1', 'Publication'), 'A Guide to Advent', 'EDITED BY', 'Jane Example',
        'COMPILED BY', 'Alex Example', '© 2014 Example Press', 'First edition',
        'Published by Example Press', 'ISBN 978-0-664-25964-8 (alk. paper)',
        ('Heading1', 'Introduction'),
        'Amber lanterns introduce the purpose of this collection.',
        'This introduction explains how to use its chapters.',
    ])
    lib = seed(root, [{'title': 'A Guide to Advent', 'author': 'Jane Example, editor', 'paths': [path],
                       'metadata': {'isbn': '9781611645286', 'publication_year': 2014,
                                    'publisher': 'Example Press', 'edition': 'First edition'}}])
    hit = lib.search('amber lanterns', engine='exact')['direct'][0]
    return lib, hit


def test_section_receives_late_publication_evidence_with_explicit_scope(guided_book):
    lib, hit = guided_book
    context = lib.review_context(hit['section_id'])
    target = [e for e in context['evidence'] if e['in_target']]
    supporting = [e for e in context['evidence'] if not e['in_target']]
    isbn = next(e for e in supporting if 'ISBN 978-' in e['text'])
    assert isbn['ordinal'] > 24
    assert isbn['scope'] == 'book' and isbn['role'] == 'publication_candidate'
    assert isbn['read_url'].startswith('/units/')
    assert all(e['scope'] == 'target' and e['role'] == 'target_text' for e in target)
    assert any(e['text'] == 'Jane Example' for e in supporting)
    assert context['target_evidence_ids'] == [e['id'] for e in target]
    assert context['coverage_complete']
    assert context['coverage']['target_blocks_total'] == context['coverage']['target_blocks_supplied'] == 3


def test_book_identity_fingerprint_is_shared_and_ignores_research_labels(guided_book):
    lib, hit = guided_book
    section = lib.review_context(hit['section_id'])
    book = lib.review_context(hit['work_id'])
    assert section['book_revision'] == book['book_revision']
    lib.annotate(hit['work_id'], {'field': 'profile', 'value': {'themes': ['hope']},
                                'origin': 'user', 'status': 'provisional', 'evidence': 'Editorial research label.'})
    assert lib.review_context(hit['work_id'])['book_revision'] == book['book_revision']
    lib.annotate(hit['work_id'], {'field': 'bibliography', 'value': {'year': '2015'},
                                'origin': 'user', 'status': 'provisional', 'evidence': 'A changed publication record.'})
    assert lib.review_context(hit['section_id'])['book_revision'] != book['book_revision']


def test_all_fields_and_categories_explain_purpose_and_effect(guided_book):
    lib, hit = guided_book
    for target in (hit['work_id'], hit['section_id'], hit['id']):
        context = lib.review_context(target)
        for field in context['fields']:
            assert field['question'].endswith('?')
            assert field['purpose'] and field['effect'] and field['action_label']
    assert set(TEXT_TYPE_GUIDE) == set(TEXT_TYPES)
    assert all(item['label'] and item['definition'] and item['example'] for item in TEXT_TYPE_GUIDE.values())
    field = next(f for f in lib.review_context(hit['section_id'])['fields'] if f['key'] == 'text_type')
    assert field['question'] == 'What kind of writing is this?'
    assert field['priority'] == 'optional'
    assert field['display_value'] == 'Not classified yet'
    assert field_education('bibliography.authors')['priority'] == 'important'


def test_supporting_excerpt_truncation_does_not_hide_complete_target(tmp_path):
    root = tmp_path / 'books'
    source = docx(root / 'Book' / 'book.docx', [
        ('Heading1', 'Publication'), 'Copyright © 2014 Example Press. ' + 'Publication note. ' * 400,
        ('Heading1', 'Introduction'), 'Violet candles introduce a brief book.',
    ])
    lib = seed(root, [{'title': 'A brief book', 'author': 'Jane Example', 'paths': [source]}])
    hit = lib.search('violet candles', engine='exact')['direct'][0]
    context = lib.review_context(hit['section_id'])
    assert any(e['fragment'] for e in context['evidence'] if not e['in_target'])
    assert context['coverage_complete'] and not context['coverage']['target_truncated']


def test_context_does_not_write_reviews_or_curation(guided_book):
    lib, hit = guided_book
    before = sorted(str(p.relative_to(lib.state)) for p in lib.state.rglob('*') if p.is_file())
    lib.review_context(hit['section_id'])
    lib.review_context(hit['work_id'])
    assert not (lib.state / 'reviews').exists()
    assert not (lib.state / 'curation.jsonl').exists()
    assert sorted(str(p.relative_to(lib.state)) for p in lib.state.rglob('*') if p.is_file()) == before
