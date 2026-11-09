"""Consulted URLs are not interchangeable evidence for reported facts."""
import json
from types import SimpleNamespace

import pytest

from book_library import review_ai as ai
from test_review_ai import context, result, response, proposal, use_client, web_response, external_proposal
from test_review_assessments import context as edition_context, sources, edition, EBOOK


def test_external_fact_cannot_borrow_identifier_from_another_sources_report(context):
    returned, _ = ai._external_sources(web_response(), ai.trusted_domains(context))
    bad = {'source_id': returned[0]['id'], 'kind': 'isbn', 'value': EBOOK}
    with pytest.raises(ValueError, match='does not occur'):
        ai._reported_facts([bad], {returned[0]['id']: returned[0]}, {returned[0]['id']}, external=True,
                           report=f'A different page reports ISBN {EBOOK}.')


def test_cross_source_isbn_pair_cannot_establish_format_relationship(edition_context, sources):
    item = edition(sources)
    # The provider mentions the e-book, but the publisher only reports print.
    item['reported_facts'].append({'source_id': 'publisher', 'kind': 'isbn', 'value': EBOOK})
    from book_library.review_assessments import validate_assessments
    assert validate_assessments({'assessments': [item]}, edition_context, sources) == []


def test_inline_markers_associate_only_the_immediate_claim(context):
    a, b = 'https://www.wjkbooks.com/a', 'https://www.perlego.com/book/b'
    first = 'Print ISBN 9780664259648. ([Publisher]('+a+'))'
    second = ' E-book ISBN 9781611645286. ([Provider]('+b+'))'
    text = first + second
    start_a, start_b = text.index('[Publisher]'), text.index('[Provider]')
    output = response({}, output_text=text, output=[{'type': 'message', 'content': [{
        'type': 'output_text', 'text': text, 'annotations': [
            {'type': 'url_citation', 'url': a, 'start_index': start_a, 'end_index': first.rindex(')')},
            {'type': 'url_citation', 'url': b, 'start_index': start_b, 'end_index': len(text)-1},
        ]}]}])
    returned, _ = ai._external_sources(output, ai.trusted_domains(context))
    by_url = {s['url']: s['cited_report_text'] for s in returned}
    assert '9780664259648' in by_url[a] and '9781611645286' not in by_url[a]
    assert '9781611645286' in by_url[b] and '9780664259648' not in by_url[b]


def test_uncited_consulted_page_remains_possible_lead(context):
    output = web_response()
    output['output'][0]['action']['sources'].append({'url': 'https://www.perlego.com/book/uncited', 'title': 'Only consulted'})
    returned, _ = ai._external_sources(output, ai.trusted_domains(context))
    source = next(s for s in returned if s['title'] == 'Only consulted')
    assert not source.get('cited_report_text')
    citation = {'source_id': source['id'], 'summary': 'A possible place to investigate.', 'quote': '', 'relationship': 'supporting_evidence', 'edition_match': True}
    lead = ai._cited_evidence([citation], {source['id']: source}, context, external=True, investigation=True)[0]
    assert lead['relationship'] == 'possible_lead' and not lead['edition_match']
    with pytest.raises(ValueError, match='no source-associated'):
        ai._cited_evidence([citation], {source['id']: source}, context, external=True)


def test_invalid_ranges_never_turn_global_report_into_source_evidence(context):
    output = web_response()
    output['output'][1]['content'][0]['annotations'][0]['end_index'] = 90000
    returned, _ = ai._external_sources(output, ai.trusted_domains(context))
    assert not returned[0].get('cited_report_text')


def test_matching_identifier_must_appear_in_the_cited_source(context):
    returned, _ = ai._external_sources(web_response(text='Another publication was published in 2015.'), ai.trusted_domains(context))
    invented_match = external_proposal(returned[0])
    accepted, unresolved = ai.validate_proposals(result([invented_match]), context, returned, external=True)
    assert not accepted and unresolved[0]['category'] == 'edition_mismatch'


def test_normalization_retains_target_scope_and_does_not_reopen_local_evidence(tmp_path, monkeypatch, context):
    context['evidence'][0].update(in_target=True, role='target_text', scope='target', ordinal=1)
    local = response(result([proposal()], [{'field': 'bibliography.year', 'reason': 'Year unavailable locally.'}]))
    normalized = response(result(unresolved=[{'field': 'title', 'reason': 'Target text absent from external records.', 'category': 'incomplete_scope'}]))
    client = use_client(monkeypatch, [local, web_response(), normalized])
    from book_library.public_config import accept_budget
    library = SimpleNamespace(state=tmp_path)
    accept_budget(library, approval_evidence='Synthetic fixture explicitly accepts review spending.')
    output = ai.suggest(library, context)
    payload = json.loads(client.calls[-1]['input'])
    assert payload['target_evidence'][0]['text'] == context['evidence'][0]['text']
    assert payload['target_evidence'][0]['role'] == 'target_text'
    assert payload['target_coverage_complete'] is True
    assert payload['local_conclusions'][0]['fields'] == ['title']
    assert not any(item['field'] == 'title' for item in output['unresolved'])
    assert ai._token_count(client.calls[-1]) <= ai.NORMALIZE_INPUT_LIMIT
    assert len(client.calls) == 3
