"""Guided choices preserve field-level safeguards and never save implicitly."""
from __future__ import annotations

import copy

import pytest

from book_library.review import ReviewConflict
from book_library.review_guidance import recommendations, preview_recommendation
from book_library.review_items import review_items
from test_correction_review import review_book, change, draft, apply


def offer(lib, target, fields=None, assessments=None, unresolved=None):
    context = lib.review_context(target)
    source = next(e for e in context['evidence'] if e['in_target'])
    suggestions = [{'field': key, 'value': value, 'rationale': 'The source supports this value.',
                    'evidence': [{'source_id': source['id'], 'quote': source['text'], 'read_url': source['read_url']}],
                    'strength': 'well_supported'} for key, value in (fields or {}).items()]
    return lib.store_review_suggestions(target, {'suggestions': suggestions, 'assessments': assessments or [],
        'unresolved': unresolved or [], 'book_revision': context['book_revision']}, revision=context['revision'])


def recs(lib, target):
    return recommendations(lib.review_context(target), lib.review_draft(target))


def decide(lib, target, rec, action, **kwargs):
    saved = lib.review_draft(target)
    return lib.decide_recommendation(target, rec['id'], action, revision=saved['revision'], expected_version=saved['version'], **kwargs)


def assessment(field='text_type', kind='field', **kwargs):
    return {'id': 'assessment-stable', 'kind': kind, 'fields': [field] if field else [], 'outcome': 'keep',
            'recommendation': 'Keep the recorded information.', 'rationale': 'It agrees with the source.',
            'strength': 'likely', 'strength_reason': 'The source supports this interpretation.', 'evidence': [],
            'reported_facts': [], **kwargs}


def test_related_updates_stage_once_without_saving_or_verifying(review_book):
    lib, _, hit, _ = review_book
    target = hit['section_id']
    offered = offer(lib, target, {'title': 'General introduction', 'bibliography.title': 'General introduction'})
    group = recs(lib, target)[0]
    before = copy.deepcopy(lib._curation())
    saved = decide(lib, target, group, 'use')
    assert set(saved['changes']) == {'title', 'bibliography.title'}
    assert saved['version'] == offered['version'] + 1
    assert not any(change['verified'] for change in saved['changes'].values())
    assert saved['next_recommendation_id'] == 'summary'
    assert lib._curation() == before
    assert recs(lib, target)[0]['status'] == 'accepted'


def test_bundle_manual_conflict_rolls_back_whole_operation(review_book):
    lib, _, hit, _ = review_book
    target = hit['section_id']
    offer(lib, target, {'title': 'General introduction', 'bibliography.title': 'General introduction'})
    draft(lib, target, {'bibliography.title': change('My carefully typed title', verified=True)})
    before = lib.review_draft(target)
    group = recs(lib, target)[0]
    with pytest.raises(ReviewConflict, match='different draft'):
        decide(lib, target, group, 'use')
    assert lib.review_draft(target) == before
    saved = decide(lib, target, group, 'use', replace=True)
    assert saved['changes']['bibliography.title']['value'] == 'General introduction'
    undone = decide(lib, target, group, 'undo')
    assert undone['changes'] == before['changes']
    assert all(i['status'] == 'pending' for i in review_items(lib.review_context(target), undone))
    repeated = decide(lib, target, group, 'undo')
    assert repeated['version'] == undone['version']


def test_individual_selection_and_undo_preserve_later_manual_work(review_book):
    lib, _, hit, _ = review_book
    target = hit['section_id']
    offer(lib, target, {'title': 'General introduction', 'bibliography.title': 'General introduction'})
    group = recs(lib, target)[0]
    chosen = next(i['id'] for i in group['items'] if i['field'] == 'bibliography.title')
    saved = decide(lib, target, group, 'use', selected_item_ids=[chosen])
    assert set(saved['changes']) == {'bibliography.title'}
    manual = draft(lib, target, {'bibliography.title': change('My later edit')})
    undone = decide(lib, target, group, 'undo')
    assert undone['changes'] == manual['changes']
    assert 'later edits' in undone['message']


def test_undo_restores_prior_decisions_and_preserves_subsequent_individual_choice(review_book):
    lib, _, hit, _ = review_book
    target = hit['section_id']
    offer(lib, target, {'title': 'General introduction', 'bibliography.title': 'General introduction'})
    group = recs(lib, target)[0]
    saved = lib.review_draft(target)
    first, second = group['items']
    lib.decide_review(target, first['id'], 'reject', revision=saved['revision'], expected_version=saved['version'])
    accepted = decide(lib, target, group, 'use')
    lib.decide_review(target, second['id'], 'later', revision=accepted['revision'], expected_version=accepted['version'])
    undone = decide(lib, target, group, 'undo')
    states = {i['id']: i['status'] for i in review_items(lib.review_context(target), undone)}
    assert states[first['id']] == 'rejected'
    assert states[second['id']] == 'later'
    assert not undone['changes']


def test_no_change_assessment_is_useful_optional_and_read_only(review_book):
    lib, _, hit, _ = review_book
    target = hit['section_id']
    offer(lib, target, assessments=[assessment()])
    before = copy.deepcopy(lib._curation())
    initial = lib.review_draft(target)
    group = recs(lib, target)[0]
    assert group['kind'] == 'keep' and group['priority'] == 'optional'
    assert group['question'] == 'What kind of writing is this?'
    assert lib.review_draft(target) == initial
    kept = decide(lib, target, group, 'use')
    assert not kept['changes'] and recs(lib, target)[0]['status'] == 'kept'
    assert lib._curation() == before
    deferred = decide(lib, target, group, 'later')
    assert recs(lib, target)[0]['status'] == 'later'
    assert deferred['next_recommendation_id'] == 'summary'
    decide(lib, target, group, 'undo')
    assert recs(lib, target)[0]['status'] == 'kept'
    offer(lib, target, assessments=[])
    assert recs(lib, target)[0]['status'] == 'kept'  # Later AI omissions retain history.


def test_optional_questions_do_not_block_finishing_important_review(review_book):
    lib, _, hit, _ = review_book
    target = hit['section_id']
    offer(lib, target, {'bibliography.title': 'General introduction'}, unresolved=[{'field': 'text_type', 'reason': 'Several interpretations are possible.'}])
    important = next(r for r in recs(lib, target) if r['priority'] == 'important')
    saved = decide(lib, target, important, 'use')
    assert saved['next_recommendation_id'] == 'summary'
    assert any(r['status'] == 'pending' and r['priority'] == 'optional' for r in recs(lib, target))


def test_keep_cannot_discard_or_verify_a_manual_draft(review_book):
    lib, _, hit, _ = review_book
    target = hit['section_id']
    offer(lib, target, assessments=[assessment()])
    saved = draft(lib, target, {'text_type': change('prose', verified=True)})
    with pytest.raises(ValueError, match='queued correction'):
        decide(lib, target, recs(lib, target)[0], 'keep')
    assert lib.review_draft(target) == saved


def test_book_comparison_from_section_has_one_home_and_preserves_book_drafts(review_book):
    lib, _, hit, _ = review_book
    section, work = hit['section_id'], hit['work_id']
    manual = draft(lib, work, {'bibliography.title': change('My book title', verified=True)})
    before = copy.deepcopy(lib._curation())
    result = offer(lib, section, assessments=[assessment(None, kind='edition', edition_relationship='related_format',
        recommendation='Keep this ISBN.', comparison={'recorded_isbn': '9780000000001', 'compared_isbn': '9780000000002',
        'relationship': 'related_format', 'records': [], 'known_differences': ['Hardback and e-book'], 'unknowns': ['Exact pagination']})])
    assert result['assessments'] == []
    assert result['book_review_notice']['url'] == '/review/' + work
    assert not any(r['kind'] == 'edition' for r in recs(lib, section))
    book = lib.review_draft(work)
    assert book['changes'] == manual['changes'] and book['revision'] == manual['revision']
    group = next(r for r in recs(lib, work) if r['kind'] == 'edition')
    assert group['comparison']['relationship'] == 'related_format'
    assert group['action_label'] == 'Keep this ISBN'
    decide(lib, work, group, 'keep')
    assert lib._curation() == before
    assert lib.review_draft(work)['changes'] == manual['changes']


def test_preview_uses_citation_rendering_without_writes(review_book):
    lib, _, hit, _ = review_book
    target = hit['section_id']
    lib.annotate(target, {'field': 'bibliography', 'value': {'type': 'chapter'},
                         'origin': 'user', 'status': 'provisional', 'evidence': 'This section is cited as a contribution.'})
    offer(lib, target, {'title': 'General introduction', 'bibliography.title': 'General introduction'})
    context, saved = lib.review_context(target), lib.review_draft(target)
    before = copy.deepcopy(lib._curation())
    preview = preview_recommendation(lib, context, saved, recs(lib, target)[0])
    assert preview['display']['after']['title'] == 'General introduction'
    assert preview['citation']['before'] == lib.cite(hit['id'])['full_note']
    assert 'General introduction' in preview['citation']['after']
    assert lib._curation() == before and lib.review_draft(target) == saved


def test_stale_version_or_foreign_selection_cannot_partially_stage(review_book):
    lib, _, hit, _ = review_book
    target = hit['section_id']
    offered = offer(lib, target, {'title': 'General introduction', 'bibliography.title': 'General introduction'})
    group = recs(lib, target)[0]
    with pytest.raises(ValueError, match='recommendation only'):
        decide(lib, target, group, 'use', selected_item_ids=['foreign'])
    with pytest.raises(ReviewConflict, match='another tab'):
        lib.decide_recommendation(target, group['id'], 'use', revision=offered['revision'], expected_version=0)
    assert lib.review_draft(target) == offered


def test_restore_after_save_reopens_review_without_reversing_curation(review_book):
    lib, _, hit, _ = review_book
    target = hit['section_id']
    offer(lib, target, {'bibliography.title': 'General introduction'})
    group = recs(lib, target)[0]
    accepted = decide(lib, target, group, 'use')
    apply(lib, target, accepted)
    before = copy.deepcopy(lib._curation())
    assert recs(lib, target)[0]['status'] == 'saved'
    restored = decide(lib, target, group, 'restore')
    assert not restored['changes'] and lib._curation() == before
    assert recs(lib, target)[0]['status'] == 'pending'


def test_competing_values_never_form_one_ambiguous_bundle(review_book):
    lib, _, hit, _ = review_book
    target = hit['section_id']
    context = lib.review_context(target)
    lib.store_review_suggestions(target, {'suggestions': [
        {'field': 'title', 'value': 'First alternative', 'rationale': 'One interpretation.', 'evidence': []},
        {'field': 'title', 'value': 'Second alternative', 'rationale': 'Another interpretation.', 'evidence': []},
        {'field': 'bibliography.title', 'value': 'Citation title', 'rationale': 'Printed heading.', 'evidence': []},
    ]}, revision=context['revision'])
    groups = recs(lib, target)
    assert len(groups) == 3 and len({r['id'] for r in groups}) == 3
    assert all(len(r['items']) == 1 for r in groups)
    first = next(r for r in groups if r['items'][0]['value'] == 'First alternative')
    second = next(r for r in groups if r['items'][0]['value'] == 'Second alternative')
    decide(lib, target, first, 'use')
    with pytest.raises(ReviewConflict, match='different draft'):
        decide(lib, target, second, 'use')
    assert lib.review_draft(target)['changes']['title']['value'] == 'First alternative'


def test_no_change_rewording_survives_but_material_value_change_reopens(review_book):
    lib, _, hit, _ = review_book
    target = hit['section_id']
    offer(lib, target, assessments=[assessment(rationale='A short source explanation.')])
    group = recs(lib, target)[0]
    decide(lib, target, group, 'keep')
    offer(lib, target, assessments=[assessment(rationale='Same conclusion, expressed differently.')])
    assert recs(lib, target)[0]['status'] == 'kept'
    lib.annotate(target, {'field': 'text_type', 'value': 'poetry', 'origin': 'user', 'status': 'provisional', 'evidence': 'A changed interpretation.'})
    current = recs(lib, target)[0]
    assert current['status'] == 'pending' and current['previous_decision']['status'] == 'kept'


def test_routed_book_comparison_retains_only_associated_sources_without_id_collisions(review_book):
    lib, _, hit, _ = review_book
    section, work = hit['section_id'], hit['work_id']
    book_context = lib.review_context(work)
    lib.store_review_suggestions(work, {'suggestions': [], 'external_report': {'text': 'Earlier book research.',
        'sources': [{'id': 'web_1', 'url': 'https://publisher.example/old', 'title': 'Earlier source'}]}}, revision=book_context['revision'])
    context = lib.review_context(section)
    edition = assessment(None, kind='edition', evidence=[{'source_id': 'web_1', 'url': 'https://publisher.example/paired'}],
        reported_facts=[{'source_id': 'web_1', 'kind': 'format', 'value': 'e-book'}],
        comparison={'records': [{'isbn': '9780000000001', 'source_ids': ['web_1']}]})
    lib.store_review_suggestions(section, {'suggestions': [], 'assessments': [edition], 'book_revision': context['book_revision'],
        'external_report': {'text': 'New research.', 'sources': [
            {'id': 'web_1', 'url': 'https://publisher.example/paired', 'title': 'Paired formats'},
            {'id': 'web_2', 'url': 'https://publisher.example/unrelated', 'title': 'Unrelated source'}]}}, revision=context['revision'])
    book = lib.review_draft(work)
    source_map = {source['id']: source for source in book['external_report']['sources']}
    assert source_map['web_1']['url'].endswith('/old')
    routed_id = book['assessments'][0]['evidence'][0]['source_id']
    assert routed_id != 'web_1' and source_map[routed_id]['url'].endswith('/paired')
    assert book['assessments'][0]['comparison']['records'][0]['source_ids'] == [routed_id]
    assert len(source_map) == 2 and book['external_report']['text'] == 'Earlier book research.'


def test_undo_second_accept_keeps_previously_accepted_part_of_bundle(review_book):
    lib, _, hit, _ = review_book
    target = hit['section_id']
    offer(lib, target, {'title': 'General introduction', 'bibliography.title': 'General introduction'})
    group = recs(lib, target)[0]
    first = group['items'][0]
    one = decide(lib, target, group, 'use', selected_item_ids=[first['id']])
    decide(lib, target, group, 'use')
    undone = decide(lib, target, group, 'undo')
    assert undone['changes'] == one['changes']
    statuses = {item['id']: item['status'] for item in review_items(lib.review_context(target), undone)}
    assert statuses[first['id']] == 'accepted'
    assert list(statuses.values()).count('pending') == 1


def test_undo_deferral_restores_prior_accepted_draft_without_losing_newer_edits(review_book):
    lib, _, hit, _ = review_book
    target = hit['section_id']
    offer(lib, target, {'bibliography.title': 'General introduction'})
    group = recs(lib, target)[0]
    accepted = decide(lib, target, group, 'use')
    deferred = decide(lib, target, group, 'later')
    assert not deferred['changes']
    undone = decide(lib, target, group, 'undo')
    assert undone['changes'] == accepted['changes']
    assert recs(lib, target)[0]['status'] == 'accepted'
    decide(lib, target, group, 'later')
    manual = draft(lib, target, {'bibliography.title': change('A later manual title')})
    undone = decide(lib, target, group, 'undo')
    assert undone['changes'] == manual['changes']


def test_omitted_no_change_assessment_reopens_after_material_change(review_book):
    lib, _, hit, _ = review_book
    target = hit['section_id']
    offer(lib, target, assessments=[assessment()])
    decide(lib, target, recs(lib, target)[0], 'keep')
    offer(lib, target)
    assert recs(lib, target)[0]['history_only'] and recs(lib, target)[0]['status'] == 'kept'
    lib.annotate(target, {'field': 'text_type', 'value': 'poetry', 'origin': 'user', 'status': 'provisional', 'evidence': 'A changed interpretation.'})
    reopened = recs(lib, target)[0]
    assert reopened['status'] == 'pending' and reopened['previous_decision']['status'] == 'kept'


def test_unresolved_assessment_is_actionable_without_duplicate_legacy_finding(review_book):
    lib, _, hit, _ = review_book
    target = hit['section_id']
    offer(lib, target, assessments=[assessment(outcome='unresolved', strength='needs_evidence',
        recommendation='Keep this category until the closing paragraph is checked.', rationale='The complete purpose is unclear.')])
    group = recs(lib, target)[0]
    assert group['kind'] == 'question' and group['reason'] == 'The complete purpose is unclear.'
    saved = decide(lib, target, group, 'later')
    assert not saved['changes'] and recs(lib, target)[0]['status'] == 'later'
