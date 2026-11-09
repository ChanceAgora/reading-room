"""Real source fixtures exercise draft/review/apply JSON contracts.

Rendered controls and focus behavior are tested by the React/browser suites.
"""
from copy import deepcopy
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from book_library.review_web import safe_link
from book_library.web import create_app
from test_service import docx, seed

ORIGIN = 'http://127.0.0.1:8765'


@pytest.fixture
def source(tmp_path):
    root = tmp_path / 'books'
    root.mkdir()
    path = docx(root / 'Review book' / 'Source.docx', [
        ('Heading1', 'Publication'), 'A Book of Introductions', 'Edited by Jane Doe',
        'Example Press, 2024', ('Heading1', 'Introduction'),
        'Copper birds gather by the river.', ('Heading1', 'Introduction'),
        'Silver bells introduce the midweek services.', '<script>alert("source")</script>',
    ])
    lib = seed(root, [{'title': 'A Book of Introductions', 'author': 'Jane Doe', 'paths': [path]}])
    first = lib.search('copper birds', engine='exact')['direct'][0]
    second = lib.search('silver bells', engine='exact')['direct'][0]
    return lib, first, second


@pytest.fixture
def client(source):
    with TestClient(create_app(source[0]), base_url=ORIGIN) as client:
        yield client


def result(response, expected=200):
    assert response.status_code == expected, response.text
    payload = response.json()
    assert payload['page'] == 'review'
    return payload['data']


def view(client, target_or_url):
    path = target_or_url if target_or_url.startswith('/') else '/review/' + target_or_url
    return result(client.get('/api/ui' + path))


def tokens(document):
    return {'revision': document['review']['revision'], 'version': str(document['draft']['version']),
            'section_offset': str(document['navigation']['section_offset']),
            'passage': document['navigation']['passage'], 'step': document['guided_step']}


def post(client, target, action, fields):
    values = dict(fields)
    csrf = values.pop('csrf', client.get('/api/ui/bootstrap').json()['csrf'])
    return client.post('/api/ui/review/' + target + '/' + action, json={'fields': values},
                       headers={'Origin': ORIGIN, 'X-CSRF-Token': csrf})


def field_values(document, key):
    field = document['field_map'][key]
    values = {**tokens(document), 'field': key, 'value': field['edit_value'], 'evidence': field['edit_evidence']}
    if field.get('edit_mode'):
        values['mode'] = field['edit_mode']
    if field.get('edit_shorts'):
        values['short_names'] = field['edit_shorts']
    if field.get('edit_verified'):
        values['verified'] = 'yes'
    if field.get('proposal_prefill'):
        values['proposal_item_id'] = field['proposal_prefill']
    return values


def add(client, target, key, value, *, evidence='', verified=False):
    fields = field_values(view(client, target), key)
    fields.update(value=value, evidence=evidence)
    fields.pop('verified', None)
    if verified:
        fields['verified'] = 'yes'
    return post(client, target, 'draft', fields)


def apply_values(document):
    fields = {**tokens(document), 'request_id': document['request_id'], 'count': str(len(document['pending']))}
    for index, pending in enumerate(document['pending']):
        fields['field_' + str(index)] = pending['field']['key']
        fields['selected_' + str(index)] = 'yes'
    return fields


def recommendation_values(document, action='use', recommendation=None):
    rec = recommendation or document['current_recommendation']
    fields = {**tokens(document), 'recommendation_id': rec['id'], 'decision': action}
    if rec.get('change_items'):
        fields.update(selection_present='yes', item_count=str(len(rec['change_items'])))
        for index, item in enumerate(rec['change_items']):
            fields['item_' + str(index)] = item['id']
            if item['id'] in rec.get('selected_item_ids', []):
                fields['selected_' + str(index)] = 'yes'
    return fields


def review_result(lib, target, *, suggestions=None, unresolved=None, external_report=None, assessments=None):
    context = lib.review_context(target)
    lib.store_review_suggestions(target, {'status': 'complete', 'suggestions': suggestions or [],
                                'unresolved': unresolved or [], 'external_report': external_report,
                                'assessments': assessments or []}, revision=context['revision'])


def choose(client, target, action, field=None):
    document = view(client, target)
    states = {'accept': {'pending'}, 'reject': {'pending'}, 'keep': {'pending'}, 'later': {'pending'},
              'restore': {'later', 'kept', 'rejected', 'saved'}, 'undo': {'accepted', 'kept', 'later'}}[action]
    item = next(item for item in document['items'] if item['status'] in states and (not field or field in (item['field'], item['field_label'])))
    return post(client, target, 'decision', {**tokens(document), 'item_id': item['id'], 'decision': action})


def test_external_sources_remain_inspectable_when_nothing_can_be_proposed(client, source):
    lib, hit, _ = source
    context = lib.review_context(hit['section_id'])
    lib.store_review_suggestions(hit['section_id'], {
        'status': 'complete', 'suggestions': [],
        'unresolved': [{'field': 'bibliography.authors', 'reason': 'The publisher describes another edition.'}],
        'cost': {'charged_or_reserved': '0.0221915', 'uncertain': False},
        'external_report': {'text': 'The edition remains uncertain.', 'sources': [
            {'url': 'https://www.wjkbooks.com/example', 'title': 'Publisher record <script>untrusted</script>'},
            {'url': 'javascript:alert(1)', 'title': 'Invalid source'},
        ]},
    }, revision=context['revision'])
    document = view(client, hit['section_id'])
    sources = document['draft']['external_report']['sources']
    assert any(safe_link(item['url']) == 'https://www.wjkbooks.com/example' for item in sources)
    assert all(not safe_link(item['url']).startswith('javascript:') for item in sources)
    assert document['draft']['suggestion_cost']['charged_or_reserved'] == '0.0221915'
    assert 'another edition' in str(document['items'])


@pytest.mark.parametrize('scope', ['work_id', 'section_id', 'id'])
def test_review_is_read_only_and_fields_have_stable_labels(client, source, scope, monkeypatch):
    lib, hit, _ = source
    from book_library import review_ai
    monkeypatch.setattr(review_ai, 'suggest', lambda *_: pytest.fail('GET must not request AI'))
    before = deepcopy(lib._curation())
    document = view(client, hit[scope])
    fields = list(document['field_map'].values())
    assert len({field['dom_id'] for field in fields}) == len(fields)
    assert all(field['label'] and field['key'] for field in fields)
    assert document['target']['scope'] in {'work', 'section', 'passage'}
    assert lib._curation() == before
    assert not (lib.state / 'costs.jsonl').exists()


def test_repeated_headings_show_different_source_context(client, source):
    _, first, second = source
    a, b = view(client, first['section_id']), view(client, second['section_id'])
    assert 'Copper birds' in a['target']['preview']
    assert 'Silver bells' in b['target']['preview']
    assert safe_link(a['target']['read_url']).startswith('/units/')


def test_manual_draft_survives_reload_without_changing_library(client, source):
    lib, hit, _ = source
    before = deepcopy(lib._curation())
    result(add(client, hit['section_id'], 'bibliography.title', 'A more precise title'))
    document = view(client, hit['section_id'])
    assert document['field_map']['bibliography.title']['edit_value'] == 'A more precise title'
    assert document['pending'][0]['proposed_display'] == 'A more precise title'
    assert not document['pending'][0]['change']['verified']
    assert lib._curation() == before


def test_final_save_is_selective_provisional_and_idempotent(client, source):
    lib, hit, _ = source
    target = hit['section_id']
    result(add(client, target, 'bibliography.title', 'Reviewed title', evidence='Heading in this edition.'))
    document = result(add(client, target, 'bibliography.short_title', 'Short title', evidence='Editorial short form.'))
    fields = apply_values(document)
    fields.pop('selected_1')
    before = len(lib._curation())
    response = result(post(client, target, 'apply', fields))
    assert 'Selected corrections saved' in response['message']
    saved = lib._curation()[before:]
    assert len(saved) == 1 and saved[0]['status'] == 'provisional'
    assert saved[0]['value'] == {'title': 'Reviewed title'}
    assert 'bibliography.short_title' in lib.review_draft(target)['changes']
    result(post(client, target, 'apply', fields))
    assert len(lib._curation()) == before + 1


def test_final_verification_is_explicit_and_preserves_other_fields(client, source):
    lib, hit, _ = source
    target = hit['section_id']
    document = result(add(client, target, 'bibliography.title', 'Verified title'))
    fields = apply_values(document)
    fields.update(evidence_0='Title verified in the actual source heading.', verified_0='yes')
    result(post(client, target, 'apply', fields))
    assert lib._curation()[-1]['status'] == 'confirmed'
    assert lib._curation()[-1]['value'] == {'title': 'Verified title'}


def test_validation_failure_preserves_final_evidence_without_applying(client, source):
    lib, hit, _ = source
    target = hit['section_id']
    result(add(client, target, 'bibliography.title', 'Changed title'))
    document = result(add(client, target, 'bibliography.short_title', 'Short'))
    fields = apply_values(document)
    fields.update(evidence_0='New <source> notes retained.', verified_0='yes')
    before = deepcopy(lib._curation())
    rejected = result(post(client, target, 'apply', fields), expected=400)
    assert rejected['pending'][0]['change']['evidence'] == fields['evidence_0']
    assert rejected['pending'][0]['change']['verified']
    assert lib._curation() == before
    assert lib.review_draft(target)['changes']['bibliography.title']['evidence'] == ''


def test_ai_request_is_protected_replayable_and_preserves_manual_drafts(client, source, monkeypatch):
    lib, hit, _ = source
    target = hit['section_id']
    result(add(client, target, 'bibliography.short_title', 'Keep my manual draft'))
    calls = []
    def generate(library, context):
        calls.append(context['target']['id'])
        evidence = next(item for item in context['evidence'] if item['in_target'])
        return {'status': 'complete', 'suggestions': [{'id': 'proposal-one', 'field': 'bibliography.title',
                 'value': 'Introduction', 'rationale': 'The source heading supplies this title.',
                 'evidence': [{'source_id': evidence['id'], 'quote': evidence['text']}]}], 'unresolved': [], 'warnings': []}
    from book_library import review_ai
    monkeypatch.setattr(review_ai, 'suggest', generate)
    document = view(client, target)
    fields = {**tokens(document), 'generation_request_id': document['request_id']}
    assert client.post('/api/ui/review/' + target + '/suggest', json={'fields': fields}).status_code == 403
    assert not calls
    before = deepcopy(lib._curation())
    result(post(client, target, 'suggest', fields))
    result(post(client, target, 'suggest', fields))
    assert calls == [target] and lib._curation() == before
    assert lib.review_draft(target)['changes']['bibliography.short_title']['value'] == 'Keep my manual draft'
    result(choose(client, target, 'accept'))
    assert lib.review_draft(target)['changes']['bibliography.title']['verified'] is False
    assert lib._curation() == before


def test_ai_unavailable_is_explained_and_manual_editing_remains(client, source, monkeypatch):
    from book_library import review_ai
    monkeypatch.setattr(review_ai, 'suggest', lambda *_: {'status': 'unavailable', 'suggestions': [], 'unresolved': [], 'warnings': ['The monthly review allowance is exhausted.']})
    target = source[1]['section_id']
    document = view(client, target)
    after = result(post(client, target, 'suggest', {**tokens(document), 'generation_request_id': document['request_id']}))
    assert 'allowance is exhausted' in str(after['draft']['suggestion_warnings'])
    assert after['field_map']


@pytest.mark.parametrize('value', ['javascript:alert(1)', 'http://[', '//evil.test', '/\\evil.test', 'https://user:pass@example.com', 'https://example.com\n/evil'])
def test_hostile_source_links_are_inert(value):
    assert safe_link(value) == ''


def test_related_title_is_separately_drafted_and_not_verified(client, source):
    lib, hit, _ = source
    target = hit['section_id']
    document = result(add(client, target, 'title', 'A specific introduction', evidence='Source heading.', verified=True))
    result(post(client, target, 'linked-title', {**tokens(document), 'source_field': 'title', 'field': 'bibliography.title'}))
    changes = lib.review_draft(target)['changes']
    assert changes['bibliography.title']['value'] == 'A specific introduction'
    assert changes['bibliography.title']['verified'] is False
    assert changes['title']['verified'] is True


def test_editing_pending_structured_names_retains_their_structure(client, source):
    lib, hit, _ = source
    target = hit['section_id']
    context = lib.review_context(target)
    lib.save_review_draft(target, {'bibliography.authors': {'value': [{'given': 'Jane', 'family': 'Doe', 'suffix': 'Jr.', 'short': 'Doe'}], 'evidence': 'Opening credit.', 'verified': False}}, revision=context['revision'], expected_version=0)
    fields = field_values(view(client, target), 'bibliography.authors')
    fields['short_names'] = 'J. Doe'
    result(post(client, target, 'draft', fields))
    assert lib.review_draft(target)['changes']['bibliography.authors']['value'][0] == {'given': 'Jane', 'family': 'Doe', 'suffix': 'Jr.', 'short': 'J. Doe'}


def test_post_action_links_reopen_at_canonical_review(client, source):
    target = source[1]['section_id']
    response = client.get('/api/ui/review/' + target + '/apply')
    assert response.status_code == 200
    assert response.json()['redirect'] == '/review/' + target + '#pending-review'


def test_guided_review_identifies_one_question_and_separates_optional_categories(client, source):
    lib, hit, _ = source
    target = hit['section_id']
    review_result(lib, target, suggestions=[
        {'field': 'bibliography.title', 'value': 'An introduction', 'rationale': 'The source heading identifies this part.', 'evidence': []},
        {'field': 'text_type', 'value': 'editorial', 'rationale': 'The full text introduces the arrangement of this book.', 'evidence': []},
    ])
    before = deepcopy(lib.review_draft(target))
    document = view(client, target)
    assert document['current_recommendation']['fields'] == ['bibliography.title']
    assert len(document['optional_guidance']) == 1
    category = view(client, document['optional_guidance'][0]['url'])
    assert 'Introduction or editorial explanation' in str(category['current_recommendation'])
    assert category['current_recommendation']['field_education']
    assert lib.review_draft(target) == before
    assert not (lib.state / 'costs.jsonl').exists()


def test_guided_bundle_preview_is_read_only_then_selected_choice_stages_and_resumes(client, source):
    lib, hit, _ = source
    target = hit['section_id']
    review_result(lib, target, suggestions=[
        {'field': 'title', 'value': 'Clear introduction', 'rationale': 'A clearer display heading.', 'evidence': []},
        {'field': 'bibliography.title', 'value': 'Introduction to the volume', 'rationale': 'A precise citation title.', 'evidence': []},
    ])
    fields = recommendation_values(view(client, target))
    assert fields['item_count'] == '2'
    fields.pop('selected_1')
    before, curation = deepcopy(lib.review_draft(target)), deepcopy(lib._curation())
    preview = result(post(client, target, 'recommendation', {**fields, 'preview': 'yes'}))
    assert 'Nothing has been queued or saved' in preview['message']
    assert preview['current_recommendation']['preview_open']
    assert preview['current_recommendation']['selected_item_ids'] == [fields['item_0']]
    assert lib.review_draft(target) == before
    after = result(post(client, target, 'recommendation', fields))
    draft = lib.review_draft(target)
    assert len(draft['changes']) == 1
    assert all(not change['verified'] for change in draft['changes'].values())
    assert lib._curation() == curation and draft['progress']['next_id']
    assert view(client, target)['guided_step'] == after['guided_step']
    undone = result(post(client, target, 'recommendation', recommendation_values(after, 'undo', after['undo_recommendation'])))
    assert not lib.review_draft(target)['changes']
    assert undone['current_recommendation']


def test_guided_keep_is_no_change_and_optional_work_can_wait(client, source):
    lib, hit, _ = source
    target = hit['section_id']
    review_result(lib, target, assessments=[{
        'id': 'keep-title', 'kind': 'field', 'fields': ['bibliography.title'], 'outcome': 'keep',
        'recommendation': 'Keep this title.', 'rationale': 'It matches the source heading.',
        'strength': 'well_supported', 'strength_reason': 'The exact heading is present.', 'evidence': [],
    }], suggestions=[{'field': 'text_type', 'value': 'editorial', 'rationale': 'It introduces the volume.', 'evidence': []}])
    document = view(client, target)
    assert document['current_recommendation']['strength_label'] == 'Well supported'
    before = deepcopy(lib._curation())
    after = result(post(client, target, 'recommendation', recommendation_values(document, 'keep')))
    assert not lib.review_draft(target)['changes'] and lib._curation() == before
    assert after['guided_step'] == 'summary' and after['summary_open']
    assert len(after['optional_guidance']) == 1


def test_guided_conflict_is_unselected_and_requires_explicit_replacement(client, source):
    lib, hit, _ = source
    target = hit['section_id']
    result(add(client, target, 'bibliography.title', 'My careful title', evidence='The complete heading.'))
    review_result(lib, target, suggestions=[{'field': 'bibliography.title', 'value': 'AI title', 'rationale': 'A source title.', 'evidence': []}])
    document = view(client, target)
    assert document['current_recommendation']['has_conflict']
    assert not document['current_recommendation']['selected_item_ids']
    fields = recommendation_values(document)
    fields['selected_0'] = 'yes'
    rejected = result(post(client, target, 'recommendation', fields), expected=400)
    assert lib.review_draft(target)['changes']['bibliography.title']['value'] == 'My careful title'
    assert 'different draft' in rejected['error'].lower()
    result(post(client, target, 'recommendation', {**fields, 'replace': 'yes'}))
    assert lib.review_draft(target)['changes']['bibliography.title']['value'] == 'AI title'


def test_book_identifier_comparison_lives_on_book_review_and_retains_source_evidence(client, source):
    lib, hit, _ = source
    review_result(lib, hit['section_id'], unresolved=[
        {'field': 'attribution', 'reason': 'ISBN records need comparison.'},
        {'field': 'attribution', 'reason': 'No named contributor is printed for this introduction.'},
    ], assessments=[{
        'id': 'format-comparison', 'kind': 'edition', 'fields': [], 'outcome': 'keep',
        'recommendation': 'Keep the recorded ISBN.', 'rationale': 'The publisher connects the print and digital formats.',
        'strength': 'well_supported', 'strength_reason': 'The publisher identifies the paired formats.', 'evidence': [],
        'edition_relationship': 'related_format', 'comparison': {
            'recorded_isbn': '9781611645286', 'compared_isbn': '9780664259648', 'relationship': 'related_format',
            'records': [
                {'isbn': '9781611645286', 'title': 'Advent Companion', 'format': 'E-book', 'publisher': 'WJK', 'year': '2014', 'edition': '', 'origin': 'Library record', 'source_ids': []},
                {'isbn': '9780664259648', 'title': '<script>record</script>', 'format': 'Hardback', 'publisher': 'WJK', 'year': '2014', 'edition': '', 'origin': 'Printed in this copy', 'source_ids': ['paired-record']},
            ], 'known_differences': ['One is a hardback; the other identifies an e-book.'],
            'unknowns': ['Identical contents have not been established.'],
        },
    }], external_report={'sources': [{'id': 'paired-record', 'title': 'Publisher: hardback and e-book', 'url': 'https://www.wjkbooks.com/example'}]})
    section = view(client, hit['section_id'])
    assert all(rec['kind'] != 'edition' for rec in section['guidance'])
    assert section['target']['work_id'] == hit['work_id']
    assert 'No named contributor is printed' in section['current_recommendation']['reason_short']
    assert 'ISBN records need comparison' not in section['current_recommendation']['reason_short']
    book = view(client, hit['work_id'])
    comparison = next(rec['comparison'] for rec in book['guidance'] if rec['kind'] == 'edition')
    assert len(comparison['records']) == 2
    assert comparison['relationship'] == 'related_format'
    assert comparison['unknowns'] == ['Identical contents have not been established.']
    assert comparison['records'][1]['title'] == '<script>record</script>'
    assert comparison['records'][1]['source_links'][0]['href'] == 'https://www.wjkbooks.com/example'


def test_guided_decision_keeps_csrf_revision_and_concurrency_boundaries(client, source):
    lib, hit, _ = source
    target = hit['section_id']
    review_result(lib, target, unresolved=[{'field': 'bibliography.authors', 'reason': 'No named contributor.'}])
    fields = recommendation_values(view(client, target), 'keep')
    assert post(client, target, 'recommendation', {**fields, 'csrf': 'incorrect'}).status_code == 403
    assert post(client, target, 'recommendation', {**fields, 'revision': 'stale'}).status_code == 400
    result(add(client, target, 'notes', 'A draft created in another tab.'))
    assert post(client, target, 'recommendation', fields).status_code == 400
    assert lib.review_draft(target)['changes']['notes']['value'] == 'A draft created in another tab.'


def test_requested_ai_review_opens_first_essential_from_empty_summary(client, source, monkeypatch):
    from book_library import review_ai
    lib, hit, _ = source
    target = hit['section_id']
    monkeypatch.setattr(review_ai, 'suggest', lambda *_: {
        'status': 'complete', 'suggestions': [],
        'unresolved': [{'field': 'bibliography.authors', 'reason': 'No explicit contributor credit.'}],
    })
    document = view(client, target)
    assert document['guided_step'] == 'summary'
    after = result(post(client, target, 'suggest', {**tokens(document), 'generation_request_id': document['request_id']}))
    assert after['current_recommendation']['fields'] == ['bibliography.authors']
    assert not lib.review_draft(target)['changes']


def test_finish_navigation_does_not_resolve_unanswered_questions(client, source):
    lib, hit, _ = source
    target = hit['section_id']
    review_result(lib, target, unresolved=[{'field': 'bibliography.authors', 'reason': 'The writer is not established.'}])
    document = view(client, target)
    before = deepcopy(lib.review_draft(target))
    after = view(client, document['summary_url'])
    assert after['current_recommendation'] is None and after['pending'] == []
    assert after['has_remaining_recommendations']
    assert lib.review_draft(target) == before


def test_related_questions_are_grouped_and_investigation_is_read_only(client, source):
    lib, hit, _ = source
    target = hit['section_id']
    review_result(lib, target, unresolved=[
        {'field': 'attribution', 'reason': 'Editors do not establish the contributor.'},
        {'field': 'text_type', 'reason': 'The excerpts do not establish the full content throughout.'},
        {'field': 'bibliography.title', 'reason': 'No citation title supplied.'},
        {'field': 'bibliography.authors', 'reason': 'No explicit author credit.'},
        {'field': 'attribution', 'reason': 'The publisher does not identify the contributor.'},
        {'field': 'bibliography.authors', 'reason': 'The publisher ISBN conflicts with this edition.'},
        {'field': 'bibliography.title', 'reason': 'The ISBN conflict leaves this edition unresolved.'},
    ])
    document = view(client, target)
    assert len(document['items']) == 4 and len(document['action_groups']) == 3
    assert document['outstanding_count'] == 4
    assert 'Editors do not establish the contributor.' in str(document['action_groups'])
    expanded = view(client, document['action_groups'][0]['investigate_url'])
    assert expanded['investigate_id'] == document['action_groups'][0]['id']
    assert any(lead['href'].startswith('/units/') for group in expanded['action_groups'] for lead in group['leads'])
    field = next(iter(expanded['field_map'].values()))
    editor = view(client, field['review_edit_url'])
    assert editor['field_map'][field['key']]['editor_open']


def test_question_decisions_are_protected_and_restore_without_metadata_changes(client, source):
    lib, hit, _ = source
    target = hit['section_id']
    review_result(lib, target, unresolved=[{'field': 'attribution', 'reason': 'No credit found.'}])
    before = deepcopy(lib._curation())
    document = view(client, target)
    fields = {**tokens(document), 'item_id': document['items'][0]['id'], 'decision': 'keep'}
    assert client.post('/api/ui/review/' + target + '/decision', json={'fields': fields}).status_code == 403
    after = result(choose(client, target, 'keep'))
    assert after['action_item_id'] == fields['item_id']
    document = view(client, target)
    assert not document['action_groups'] and document['handled'][0]['status'] == 'kept'
    result(choose(client, target, 'restore'))
    result(choose(client, target, 'later'))
    document = view(client, target)
    assert document['outstanding_count'] == document['deferred_count'] == 1
    assert document['deferred'][0]['status'] == 'later'
    assert lib._curation() == before


def test_accept_collision_requires_explicit_replacement_and_undo_restores_draft(client, source):
    lib, hit, _ = source
    target = hit['section_id']
    result(add(client, target, 'bibliography.title', 'My title', evidence='Manual evidence.', verified=True))
    context = lib.review_context(target)
    evidence = next(e for e in context['evidence'] if e['in_target'])
    review_result(lib, target, suggestions=[{'id': 'old-proposal', 'field': 'bibliography.title', 'value': 'Source title',
                  'rationale': 'Heading.', 'evidence': [{'source_id': evidence['id'], 'quote': evidence['text']}]}])
    document = view(client, target)
    item = document['items'][0]
    assert item['draft_conflict']
    fields = {**tokens(document), 'item_id': item['id'], 'decision': 'accept', 'replace': 'yes'}
    result(post(client, target, 'decision', fields))
    assert lib.review_draft(target)['changes']['bibliography.title']['value'] == 'Source title'
    assert not lib.review_draft(target)['changes']['bibliography.title']['verified']
    result(choose(client, target, 'undo'))
    assert lib.review_draft(target)['changes']['bibliography.title'] == {'value': 'My title', 'evidence': 'Manual evidence.', 'verified': True}


def test_legacy_use_route_cannot_overwrite_manual_draft(client, source):
    lib, hit, _ = source
    target = hit['section_id']
    result(add(client, target, 'bibliography.title', 'Keep this', evidence='Manual.'))
    review_result(lib, target, suggestions=[{'id': 'legacy-id', 'field': 'bibliography.title', 'value': 'Other title', 'rationale': 'Source heading.', 'evidence': []}])
    response = post(client, target, 'use-suggestion', {**tokens(view(client, target)), 'suggestion_id': 'legacy-id'})
    assert response.status_code == 400
    assert lib.review_draft(target)['changes']['bibliography.title']['value'] == 'Keep this'


def test_evidence_verification_resets_after_edit_and_final_save_stays_provisional(client, source):
    lib, hit, _ = source
    target = hit['section_id']
    document = result(add(client, target, 'bibliography.title', 'First title', evidence='Heading.'))
    fields = {**tokens(document), 'count': '1', 'field_0': 'bibliography.title', 'evidence_0': 'Heading.', 'verified_0': 'yes'}
    result(post(client, target, 'draft-evidence', fields))
    document = view(client, target)
    assert document['pending'][0]['change']['verified']
    fields = field_values(document, 'bibliography.title')
    fields['value'] = 'Second title'
    after = result(post(client, target, 'draft', fields))
    assert not lib.review_draft(target)['changes']['bibliography.title']['verified']
    result(post(client, target, 'apply', apply_values(after)))
    assert lib._curation()[-1]['status'] == 'provisional'


def test_history_keeps_validated_source_link_after_new_review_replaces_external_report(client, source):
    lib, hit, _ = source
    target = hit['section_id']
    url = 'https://www.wjkbooks.com/checked-record'
    review_result(lib, target, unresolved=[{'field': 'bibliography.authors', 'reason': 'Record is inconclusive.',
                  'evidence': [{'source_id': 'external-1', 'url': url, 'summary': 'No section credit.', 'relationship': 'checked_inconclusive'}]}],
                  external_report={'sources': [{'id': 'external-1', 'url': url, 'title': 'Publisher record'}]})
    result(choose(client, target, 'keep'))
    review_result(lib, target)
    document = view(client, target)
    evidence = next(item for record in document['handled'] for item in record['evidence_items'] if item['href'] == url)
    assert evidence['link_help'] == 'Evidence from a previous review; recheck before relying on it.'


def test_edit_suggestion_is_unsaved_prefill_and_retains_structured_names(client, source):
    lib, hit, _ = source
    target = hit['section_id']
    context = lib.review_context(target)
    evidence = next(e for e in context['evidence'] if e['in_target'])
    names = [{'given': 'Jane', 'family': 'Doe', 'suffix': 'Jr.', 'short': 'Doe'}]
    review_result(lib, target, suggestions=[{'id': 'named-proposal', 'field': 'bibliography.authors', 'value': names,
                  'rationale': 'Signed contribution.', 'evidence': [{'source_id': evidence['id'], 'quote': evidence['text']}]}])
    before = deepcopy(lib.review_draft(target))
    document = view(client, target)
    editor = view(client, document['items'][0]['proposal_edit_url'])
    field = editor['field_map']['bibliography.authors']
    assert field['edit_value'] == 'Jane Doe, Jr.'
    assert evidence['text'] in field['edit_evidence']
    assert not field['edit_verified']
    assert lib.review_draft(target) == before
    fields = field_values(editor, 'bibliography.authors')
    fields['short_names'] = 'J. Doe'
    result(post(client, target, 'draft', fields))
    saved = lib.review_draft(target)['changes']['bibliography.authors']
    assert saved['value'] == [{'given': 'Jane', 'family': 'Doe', 'suffix': 'Jr.', 'short': 'J. Doe'}]
    assert not saved['verified'] and not lib._curation()


def test_suggestion_prefill_preserves_manual_draft_and_rejects_stale_proposal(client, source):
    lib, hit, _ = source
    target = hit['section_id']
    review_result(lib, target, suggestions=[{'id': 'title-proposal', 'field': 'bibliography.title', 'value': 'Proposed title',
                  'rationale': 'Heading.', 'evidence': []}])
    edit_url = view(client, target)['items'][0]['proposal_edit_url']
    result(add(client, target, 'bibliography.title', 'Manual title', evidence='Keep manual.'))
    editor = view(client, edit_url)
    assert 'existing draft differs' in editor['error']
    assert 'proposal_prefill' not in editor['field_map']['bibliography.title']
    assert editor['field_map']['bibliography.title']['edit_value'] == 'Manual title'
    draft = lib.review_draft(target)
    lib.rebase_review_draft(target, expected_version=draft['version'])
    editor = view(client, edit_url)
    assert 'no longer current' in editor['error']
    assert 'proposal_prefill' not in editor['field_map']['bibliography.title']


def test_field_validation_identifies_control_and_keeps_unsaved_input(client, source):
    target = source[1]['section_id']
    document = result(add(client, target, 'title', ''), expected=400)
    assert document['error_field'] == 'title'
    assert document['error']
    assert document['field_map']['title']['unsaved']
    assert document['field_map']['title']['edit_value'] == ''


def test_edited_suggestion_acceptance_resolves_original_item_and_preserves_explicit_verification(client, source):
    lib, hit, _ = source
    target = hit['section_id']
    review_result(lib, target, suggestions=[{'id': 'proposal-to-edit', 'field': 'bibliography.title', 'value': 'Original proposed title',
                  'rationale': 'Source heading.', 'evidence': []}])
    edit_url = view(client, target)['items'][0]['proposal_edit_url']
    editor = view(client, edit_url)
    fields = field_values(editor, 'bibliography.title')
    fields.update(value='My edited title', evidence='Verified exact title in the source heading.', verified='yes')
    after = result(post(client, target, 'draft', fields))
    assert lib.review_draft(target)['changes']['bibliography.title'] == {'value': 'My edited title', 'evidence': fields['evidence'], 'verified': True}
    assert after['outstanding_count'] == 0 and len(after['pending']) == 1
    assert after['items'][0]['status_label'] == 'Accepted after editing'
    reloaded = view(client, target)
    assert not reloaded['action_groups']
    assert reloaded['pending'][0]['proposed_display'] == 'My edited title'
    assert not lib._curation()
    result(choose(client, target, 'undo'))
    assert lib.review_draft(target)['changes'] == {}
    assert view(client, target)['items'][0]['proposed_display'] == 'Original proposed title'
