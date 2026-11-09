"""Guidance is a bounded explanation, never an inferred correction or verification."""
import copy

import pytest

from book_library import review_assessments as assessment


PRINT = '9780664259648'
EBOOK = '9781611645286'
TITLE = 'Feasting on the Word Advent Companion'


@pytest.fixture
def context():
    return {'target': {'id': 'section_intro', 'work_id': 'work_advent', 'scope': 'section',
                       'title': 'Introduction', 'work_title': TITLE,
                       'copy_format': 'EPUB', 'source_origin': 'Bookshare accessible export'},
            'fields': [{'key': 'bibliography.isbn', 'value': EBOOK},
                       {'key': 'bibliography.year', 'value': '2014'},
                       {'key': 'bibliography.publisher', 'value': 'Westminster John Knox Press'},
                       {'key': 'text_type', 'value': 'prose'}],
            'external_report_text': f'Publisher: {TITLE}, ISBN {PRINT}, Hardback, First edition, 2014. '
                f'Perlego: {TITLE}, print ISBN {PRINT}, eBook ISBN {EBOOK}, First edition, 2014.',
            'revision': 'section_revision', 'book_revision': 'book_revision'}


@pytest.fixture
def sources():
    return [{'id': 'copyright', 'text': f'{TITLE}\nFirst edition\n2014\nISBN 978-0-664-25964-8 (alk. paper)',
             'read_url': '/units/copy#copyright', 'in_target': False, 'role': 'publication_candidate'},
            {'id': 'publisher', 'url': 'https://www.wjkbooks.com/bookproduct/advent/', 'source_kind': 'publisher',
             'cited_report_text': f'{TITLE}, ISBN {PRINT}, Hardback, First edition, 2014.'},
            {'id': 'provider', 'url': 'https://www.perlego.com/book/2100938/advent', 'source_kind': 'ebook_provider',
             'cited_report_text': f'{TITLE}, print ISBN {PRINT}, eBook ISBN {EBOOK}, First edition, 2014.'}]


def fact(source, kind, value, number=''):
    return {'source_id': source, 'kind': kind, 'value': value, 'record_isbn': number}


def edition(sources):
    return {'kind': 'edition', 'fields': [], 'outcome': 'keep', 'recommendation': 'Keep this ISBN.',
            'rationale': 'These publication records describe print and ebook formats.',
            'strength': 'well_supported', 'strength_reason': 'Identifiers occur in the cited records.',
            'edition_relationship': 'related_format',
            'evidence': [{'source_id': 'copyright', 'quote': f'ISBN 978-0-664-25964-8 (alk. paper)', 'summary': ''},
                         {'source_id': 'publisher', 'quote': '', 'summary': 'Publisher identifies the printed book.'},
                         {'source_id': 'provider', 'quote': '', 'summary': 'Provider pairs the print and ebook identifiers.'}],
            'reported_facts': [fact('copyright', 'isbn', PRINT), fact('copyright', 'title', TITLE, PRINT),
                fact('copyright', 'edition', 'First edition', PRINT), fact('copyright', 'year', '2014', PRINT),
                fact('publisher', 'isbn', PRINT), fact('publisher', 'format', 'Hardback', PRINT),
                fact('provider', 'isbn', PRINT), fact('provider', 'isbn', EBOOK),
                fact('provider', 'format', 'eBook', EBOOK)]}


def test_advent_print_and_ebook_are_related_formats_with_canonical_book_scope(context, sources):
    output = assessment.validate_assessments({'assessments': [edition(sources)]}, context, sources)
    item = output[0]
    assert item['edition_relationship'] == 'related_format'
    assert item['scope'] == 'book' and item['target_id'] == 'work_advent'
    assert item['outcome'] == 'keep' and item['strength'] == 'likely'
    compared = item['comparison']
    assert [r['isbn'] for r in compared['records']] == [EBOOK, PRINT]
    assert [r['format'] for r in compared['records']] == ['eBook', 'Hardback']
    assert [r['origin'] for r in compared['records']] == ['Library record', 'Printed in this copy']
    assert compared['copy_note'] == 'Bookshare accessible export · EPUB'
    assert 'transferable page numbers' in compared['unknowns'][-1]
    assert 'Bookshare' not in compared['records'][0]['format']
    assert all('quote' not in e for e in item['evidence'] if e.get('url'))


def test_identifier_difference_alone_is_unknown_not_an_edition_conflict(context, sources):
    output = assessment.local_edition_fallback(context, sources[:1])
    assert output[0]['edition_relationship'] == 'unknown'
    assert output[0]['strength'] == 'needs_evidence'
    assert output[0]['comparison']['records'][0]['format'] == ''
    assert output[0]['recommendation'] == 'Keep the recorded ISBN for now.'


def test_isbn10_and_isbn13_are_the_same_publication(context):
    context['fields'][0]['value'] = PRINT
    source = {'id': 'copyright', 'text': 'ISBN 0-664-25964-2'}
    compared = assessment.comparison(context, [], [source])
    assert compared['relationship'] == 'same_publication'
    assert compared['compared_isbn'] == '' and len(compared['records']) == 1
    assert assessment.isbn('9780000000000') == ''
    assert assessment.isbn('0000000000000') == ''


def test_different_editions_require_actual_distinct_edition_statements(context, sources):
    facts = [fact('copyright', 'isbn', PRINT), fact('copyright', 'edition', 'First edition', PRINT),
             fact('provider', 'isbn', EBOOK), fact('provider', 'edition', 'Second edition', EBOOK)]
    compared = assessment.comparison(context, facts, sources, 'different_edition')
    assert compared['relationship'] == 'different_edition'
    facts[-1]['value'] = '1st edition'
    assert assessment.comparison(context, facts, sources, 'different_edition')['relationship'] == 'unknown'


def test_provider_single_format_is_not_assigned_to_both_paired_identifiers(context, sources):
    facts = [fact('provider', 'isbn', PRINT), fact('provider', 'isbn', EBOOK),
             fact('provider', 'format', 'eBook')]
    compared = assessment.comparison(context, facts, sources)
    assert compared['relationship'] == 'unknown'
    assert not any(record['format'] for record in compared['records'])


def test_paired_formats_cannot_hide_an_edition_conflict(context, sources):
    facts = [fact('provider', 'isbn', PRINT), fact('provider', 'isbn', EBOOK),
             fact('provider', 'format', 'Hardback', PRINT), fact('provider', 'format', 'eBook', EBOOK),
             fact('copyright', 'edition', 'First edition', PRINT), fact('provider', 'edition', 'Second edition', EBOOK)]
    compared = assessment.comparison(context, facts, sources, 'related_format')
    assert compared['relationship'] == 'unknown'
    assert any('edition statements differ' in reason for reason in compared['unknowns'])


def test_copy_and_publisher_precedence_retains_conflict_explanation(context, sources):
    facts = [fact('copyright', 'isbn', PRINT), fact('copyright', 'edition', 'First edition', PRINT),
             fact('provider', 'isbn', PRINT), fact('provider', 'edition', 'Second edition', PRINT)]
    compared = assessment.comparison(context, facts, sources)
    assert compared['records'][1]['edition'] == 'First edition'
    assert any('Records disagree about edition' in line for line in compared['unknowns'])


@pytest.mark.parametrize('bad', ['invented_source', 'invented_fact', 'external_quote', 'unsafe_url', 'wrong_record_isbn'])
def test_unsupported_assessment_evidence_never_becomes_a_recommendation(context, sources, bad):
    item = edition(sources)
    if bad == 'invented_source':
        item['evidence'][0]['source_id'] = 'invented'
    elif bad == 'invented_fact':
        item['reported_facts'][2]['value'] = 'Revised edition'
    elif bad == 'external_quote':
        item['evidence'][1]['quote'] = 'A supposed publisher quotation'
    elif bad == 'unsafe_url':
        sources[1]['url'] = 'https://wjkbooks.com.evil.test/book'
    else:
        item['reported_facts'][2]['record_isbn'] = EBOOK
    assert not assessment.validate_assessments({'assessments': [item]}, context, sources)


def test_no_change_assessment_is_not_a_correction_or_verification(context, sources):
    item = {'kind': 'field', 'fields': ['text_type'], 'outcome': 'keep',
            'recommendation': 'Keep ordinary prose.', 'rationale': 'The paragraph is continuous prose.',
            'strength': 'likely', 'strength_reason': 'This is a judgment about the inspected writing.',
            'evidence': [{'source_id': 'intro', 'quote': 'This introduction explains the book.', 'summary': ''}],
            'reported_facts': [], 'edition_relationship': 'unknown'}
    sources.append({'id': 'intro', 'text': 'This introduction explains the book.', 'in_target': True})
    before = copy.deepcopy(context)
    output = assessment.validate_assessments({'assessments': [item]}, context, sources)
    assert output[0]['outcome'] == 'keep'
    assert 'value' not in output[0] and 'verified' not in output[0]
    assert context == before
    item['outcome'] = 'change'
    assert assessment.validate_assessments({'assessments': [item]}, context, sources)[0]['outcome'] == 'unresolved'
