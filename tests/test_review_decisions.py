"""Compact review actions are durable workflow state, never implicit curation."""
from __future__ import annotations

import copy

import pytest

from book_library.review import ReviewConflict
from book_library.review_items import review_items
from book_library.storage import atomic_json, read_json
from test_correction_review import review_book, change, draft, apply
from test_service import docx


def offer(lib, target, *, value='A revised Introduction', reason='Printed heading inspected.', unresolved=None):
    context = lib.review_context(target)
    source = next(e for e in context['evidence'] if e['in_target'])
    result = {'suggestions': [{'id': 'generation-specific-id', 'field': 'bibliography.title', 'value': value,
                              'rationale': reason, 'evidence': [{'source_id': source['id'], 'quote': source['text'],
                                                               'read_url': source['read_url']}]}],
              'unresolved': unresolved or [], 'status': 'complete'}
    return lib.store_review_suggestions(target, result, revision=context['revision'])


def items(lib, target):
    return review_items(lib.review_context(target), lib.review_draft(target))


def decide(lib, target, item, action, **kwargs):
    saved = lib.review_draft(target)
    return lib.decide_review(target, item['id'], action, revision=saved['revision'], expected_version=saved['version'], **kwargs)


def question(field='bibliography.authors', reason='No section credit was established.', **kwargs):
    return {'field': field, 'reason': reason, **kwargs}


def test_accept_is_separate_from_save_and_verification(review_book):
    lib, _, hit, _ = review_book
    target = hit['section_id']
    offer(lib, target)
    before = copy.deepcopy(lib._curation())
    suggestion = items(lib, target)[0]
    saved = decide(lib, target, suggestion, 'accept')
    assert not saved['changes']['bibliography.title']['verified']
    assert items(lib, target)[0]['status'] == 'accepted'
    assert lib._curation() == before
    repeated = decide(lib, target, suggestion, 'accept')
    assert repeated['version'] == saved['version']
    result = apply(lib, target, saved)
    assert result['saved']
    assert items(lib, target)[0]['status'] == 'saved'
    assert lib._curation()[-1]['status'] == 'provisional'


def test_duplicate_advent_questions_merge_without_losing_reasons(review_book):
    lib, _, hit, _ = review_book
    target = hit['section_id']
    findings = [question('attribution', 'Book editors do not identify this contributor.'),
                question('text_type', 'The whole section was not inspected.'),
                question('bibliography.title', 'Section citation title is missing.'),
                question(), question('attribution', 'Publisher does not identify this contributor.'),
                question('bibliography.authors', 'The external ISBN differs.'),
                question('bibliography.title', 'The external edition differs.')]
    context = lib.review_context(target)
    lib.store_review_suggestions(target, {'suggestions': [], 'unresolved': findings}, revision=context['revision'])
    projected = items(lib, target)
    assert len(projected) == 4
    assert sum(len(i['reasons']) for i in projected) == 7
    next_findings = [question(), question('attribution'), question(), question('attribution', 'Different edition.')]
    lib.store_review_suggestions(target, {'suggestions': [], 'unresolved': next_findings}, revision=context['revision'])
    assert len(items(lib, target)) == 2
    assert sum(len(i['reasons']) for i in items(lib, target)) == 3


@pytest.mark.parametrize('action,status', [('reject', 'rejected'), ('later', 'later')])
def test_proposal_workflow_decisions_can_be_restored_without_curation(review_book, action, status):
    lib, _, hit, _ = review_book
    target = hit['section_id']
    offer(lib, target)
    before = lib._curation()
    item = items(lib, target)[0]
    decide(lib, target, item, action)
    assert items(lib, target)[0]['status'] == status
    decide(lib, target, item, 'restore')
    assert items(lib, target)[0]['status'] == 'pending'
    assert lib._curation() == before
    assert not lib.review_draft(target)['changes']


def test_keep_and_later_questions_neither_change_nor_verify_values(review_book):
    lib, _, hit, _ = review_book
    target = hit['section_id']
    offer(lib, target, unresolved=[question()])
    item = next(i for i in items(lib, target) if i['kind'] == 'question')
    original = lib.review_context(target)
    decide(lib, target, item, 'later')
    assert next(i for i in items(lib, target) if i['kind'] == 'question')['status'] == 'later'
    decide(lib, target, item, 'keep')
    assert next(i for i in items(lib, target) if i['kind'] == 'question')['status'] == 'kept'
    assert lib.review_context(target)['fields'] == original['fields']
    with pytest.raises(ValueError, match='Unanswered questions'):
        decide(lib, target, item, 'accept')


def test_decisions_survive_regeneration_rephrasing_and_draft_discard(review_book):
    lib, _, hit, _ = review_book
    target = hit['section_id']
    offer(lib, target, unresolved=[question()])
    proposal, unresolved = items(lib, target)
    decide(lib, target, proposal, 'reject')
    decide(lib, target, unresolved, 'keep')
    offer(lib, target, reason='The same heading has different explanatory wording.',
          unresolved=[question(reason='Authorship remains unestablished in the source.')])
    assert {i['status'] for i in items(lib, target)} == {'rejected', 'kept'}
    saved = draft(lib, target, {'notes': change('A manual note')})
    lib.discard_review_draft(target, expected_version=saved['version'])
    assert not lib.review_draft(target)['changes']
    assert {i['status'] for i in items(lib, target)} == {'rejected', 'kept'}


def test_history_survives_replacement_of_ai_arrays(review_book):
    lib, _, hit, _ = review_book
    target = hit['section_id']
    offer(lib, target)
    original = items(lib, target)[0]
    decide(lib, target, original, 'reject')
    context = lib.review_context(target)
    lib.store_review_suggestions(target, {'suggestions': [], 'unresolved': []}, revision=context['revision'])
    preserved = items(lib, target)[0]
    assert preserved['id'] == original['id'] and preserved['status'] == 'rejected'
    assert preserved['from_history']


def test_accept_collision_requires_choice_and_undo_restores_manual_draft(review_book):
    lib, _, hit, _ = review_book
    target = hit['section_id']
    offer(lib, target)
    manual = draft(lib, target, {'bibliography.title': change('My own title', verified=True)})
    item = items(lib, target)[0]
    with pytest.raises(ReviewConflict, match='different draft'):
        decide(lib, target, item, 'accept')
    assert lib.review_draft(target)['changes'] == manual['changes']
    decide(lib, target, item, 'accept', replace=True)
    assert not lib.review_draft(target)['changes']['bibliography.title']['verified']
    decide(lib, target, item, 'undo')
    assert lib.review_draft(target)['changes'] == manual['changes']


def test_undo_preserves_manual_edits_made_after_acceptance(review_book):
    lib, _, hit, _ = review_book
    target = hit['section_id']
    offer(lib, target)
    item = items(lib, target)[0]
    decide(lib, target, item, 'accept')
    edited = draft(lib, target, {'bibliography.title': change('My improved title', verified=True)})
    undone = decide(lib, target, item, 'undo')
    assert undone['changes'] == edited['changes']
    assert 'edited draft has been kept' in undone['message']
    assert items(lib, target)[0]['status'] == 'pending'


def test_keep_does_not_discard_a_queued_change(review_book):
    lib, _, hit, _ = review_book
    target = hit['section_id']
    offer(lib, target, unresolved=[question()])
    saved = draft(lib, target, {'bibliography.authors': change([{'literal': 'Writer'}])})
    item = next(i for i in items(lib, target) if i['kind'] == 'question')
    with pytest.raises(ValueError, match='queued correction'):
        decide(lib, target, item, 'keep')
    assert lib.review_draft(target)['changes'] == saved['changes']


def test_discard_and_remove_reopen_accepted_items(review_book):
    lib, _, hit, _ = review_book
    target = hit['section_id']
    offer(lib, target)
    item = items(lib, target)[0]
    saved = decide(lib, target, item, 'accept')
    lib.discard_review_draft(target, expected_version=saved['version'])
    assert items(lib, target)[0]['status'] == 'pending'
    decide(lib, target, item, 'accept')
    draft(lib, target, {})
    assert items(lib, target)[0]['status'] == 'pending'


def test_relevant_facts_reopen_but_unrelated_metadata_does_not(review_book):
    lib, _, hit, _ = review_book
    target = hit['section_id']
    offer(lib, target, unresolved=[question()])
    item = next(i for i in items(lib, target) if i['kind'] == 'question')
    decide(lib, target, item, 'keep')
    lib.annotate(target, {'field': 'profile', 'value': {'themes': ['hope']}, 'origin': 'user',
                         'status': 'confirmed', 'evidence': 'Unrelated research label.'})
    unchanged = next(i for i in items(lib, target) if i['kind'] == 'question')
    assert unchanged['status'] == 'kept' and not unchanged['reopened']
    lib.annotate(target, {'field': 'bibliography', 'value': {'authors': [{'literal': 'Named Writer'}]},
                         'origin': 'user', 'status': 'provisional', 'evidence': 'A newly inspected credit.'})
    reopened = next(i for i in items(lib, target) if i['kind'] == 'question')
    assert reopened['status'] == 'pending' and reopened['reopened']
    assert reopened['previous_decision']['decision'] == 'kept'


def test_field_fingerprint_ignores_prose_but_detects_source_edition_and_reported_facts(review_book):
    lib, _, hit, _ = review_book
    target = hit['section_id']
    offer(lib, target, unresolved=[question(category='edition_mismatch', reported_facts=[{'source_id': 'ext1', 'kind': 'isbn', 'value': '111'}])])
    item = next(i for i in items(lib, target) if i['kind'] == 'question')
    decide(lib, target, item, 'keep')
    context, saved = lib.review_context(target), lib.review_draft(target)
    reworded = copy.deepcopy(saved)
    reworded['unresolved'][0]['reason'] = 'Different wording.'
    assert next(i for i in review_items(context, reworded) if i['kind'] == 'question')['status'] == 'kept'
    for mutate in (lambda c: c.update(source_fingerprint='new source content'),
                   lambda c: c['book_identifiers'].update(isbn='222')):
        changed = copy.deepcopy(context)
        mutate(changed)
        assert next(i for i in review_items(changed, saved) if i['kind'] == 'question')['reopened']
    reworded['unresolved'][0]['reported_facts'][0]['value'] = '222'
    assert next(i for i in review_items(context, reworded) if i['kind'] == 'question')['reopened']


def test_reported_fact_formatting_does_not_reopen_a_question(review_book):
    lib, _, hit, _ = review_book
    target = hit['section_id']
    offer(lib, target, unresolved=[question(reported_facts=[
        {'source_id': 'ext1', 'kind': 'isbn', 'value': '978-1-61164-528-6'},
        {'source_id': 'ext1', 'kind': 'publisher', 'value': 'Example Press'}])])
    item = next(i for i in items(lib, target) if i['kind'] == 'question')
    decide(lib, target, item, 'keep')
    context, changed = lib.review_context(target), lib.review_draft(target)
    changed['unresolved'][0].update(category='other', reported_facts=[
        {'source_id': 'ext1', 'kind': 'publisher', 'value': ' EXAMPLE  PRESS '},
        {'source_id': 'ext1', 'kind': 'isbn', 'value': '9781611645286'}])
    assert next(i for i in review_items(context, changed) if i['kind'] == 'question')['status'] == 'kept'


def test_replacing_an_accepted_proposal_has_one_acceptance_and_safe_undo(review_book):
    lib, _, hit, _ = review_book
    target = hit['section_id']
    offer(lib, target, value='First title')
    first = items(lib, target)[0]
    decide(lib, target, first, 'accept')
    offer(lib, target, value='Second title')
    second = next(i for i in items(lib, target) if i['value'] == 'Second title')
    decide(lib, target, second, 'accept', replace=True)
    accepted = [i for i in items(lib, target) if i['status'] == 'accepted']
    assert len(accepted) == 1 and accepted[0]['value'] == 'Second title'
    decide(lib, target, second, 'undo')
    accepted = [i for i in items(lib, target) if i['status'] == 'accepted']
    assert len(accepted) == 1 and accepted[0]['value'] == 'First title'
    assert lib.review_draft(target)['changes']['bibliography.title']['value'] == 'First title'


def test_saved_history_identifies_the_actual_manually_edited_value(review_book):
    lib, _, hit, _ = review_book
    target = hit['section_id']
    offer(lib, target, value='Original AI title')
    decide(lib, target, items(lib, target)[0], 'accept')
    saved = draft(lib, target, {'bibliography.title': change('Manually corrected title', evidence='Manually inspected source.')})
    assert items(lib, target)[0]['edited']
    assert items(lib, target)[0]['queued_value'] == 'Manually corrected title'
    apply(lib, target, saved)
    item = items(lib, target)[0]
    assert item['status'] == 'saved' and item['edited']
    assert item['saved_value'] == 'Manually corrected title'
    assert item['saved_evidence'] == 'Manually inspected source.'


def test_saved_receipt_stays_quiet_but_fresh_proposal_reopens_after_relevant_change(review_book):
    lib, _, hit, _ = review_book
    target = hit['section_id']
    offer(lib, target, value='Title A')
    original = items(lib, target)[0]
    accepted = decide(lib, target, original, 'accept')
    apply(lib, target, accepted)
    lib.annotate(target, {'field': 'bibliography', 'value': {'title': 'Title C'},
                         'origin': 'user', 'status': 'confirmed', 'evidence': 'Later source inspection.'})
    # The old stale result remains a receipt, not a new proposed correction.
    assert items(lib, target)[0]['status'] == 'saved'
    saved = lib.review_draft(target)
    lib.rebase_review_draft(target, expected_version=saved['version'])
    context = lib.review_context(target)
    lib.store_review_suggestions(target, {'suggestions': [], 'unresolved': []}, revision=context['revision'])
    historical = items(lib, target)[0]
    assert historical['from_history'] and historical['status'] == 'saved'
    # A genuinely fresh result for the same stable identity must be reviewed.
    offer(lib, target, value='Title A', reason='New review supports this title.')
    fresh = items(lib, target)[0]
    assert fresh['id'] == original['id']
    assert fresh['status'] == 'pending' and fresh['reopened'] and not fresh['stale']
    assert fresh['previous_decision']['decision'] == 'saved'
    assert 'saved_value' not in fresh
    assert decide(lib, target, fresh, 'accept')['changes']['bibliography.title']['value'] == 'Title A'


def test_explicit_edited_acceptance_queues_one_item_and_undo_preserves_manual_work(review_book):
    lib, _, hit, _ = review_book
    target = hit['section_id']
    offer(lib, target, value='Original suggestion')
    item = items(lib, target)[0]
    before = copy.deepcopy(lib._curation())
    accepted = decide(lib, target, item, 'accept', edited_change=change('Edited suggestion', verified=True))
    assert len(items(lib, target)) == 1
    assert items(lib, target)[0]['status'] == 'accepted'
    assert items(lib, target)[0]['queued_value'] == 'Edited suggestion'
    assert items(lib, target)[0]['edited']
    assert accepted['changes']['bibliography.title']['verified']
    assert 'Accepted after editing' in accepted['message']
    assert lib._curation() == before
    decide(lib, target, item, 'undo')
    assert lib.review_draft(target)['changes'] == {}
    decide(lib, target, item, 'accept', edited_change=change('Edited suggestion'))
    later = draft(lib, target, {'bibliography.title': change('Later manual work')})
    decide(lib, target, item, 'undo')
    assert lib.review_draft(target)['changes'] == later['changes']


def test_edited_acceptance_validates_atomically_and_requires_manual_replacement_choice(review_book):
    lib, _, hit, _ = review_book
    target = hit['section_id']
    offer(lib, target)
    item = items(lib, target)[0]
    manual = draft(lib, target, {'bibliography.title': change('Existing manual work')})
    with pytest.raises(ReviewConflict, match='different draft'):
        decide(lib, target, item, 'accept', edited_change=change('Edited suggestion'))
    with pytest.raises(ValueError):
        decide(lib, target, item, 'accept', edited_change={'value': ['Invalid title'], 'evidence': '', 'verified': False}, replace=True)
    assert lib.review_draft(target)['changes'] == manual['changes']
    assert not lib.review_draft(target)['decisions']
    decide(lib, target, item, 'accept', edited_change=change('Edited suggestion'), replace=True)
    decide(lib, target, item, 'undo')
    assert lib.review_draft(target)['changes'] == manual['changes']


def test_historical_proposal_cannot_be_accepted_after_source_changes(review_book):
    lib, source, hit, _ = review_book
    target = hit['work_id']
    offer(lib, target)
    original = items(lib, target)[0]
    decide(lib, target, original, 'reject')
    context = lib.review_context(target)
    lib.store_review_suggestions(target, {'suggestions': [], 'unresolved': []}, revision=context['revision'])
    docx(source, [('Heading1', 'Publication details'), 'Changed content and a different printed heading.'])
    lib.sync(semantic=False)
    old = lib.review_draft(target)
    lib.rebase_review_draft(target, expected_version=old['version'])
    historical = items(lib, target)[0]
    assert historical['from_history'] and historical['reopened'] and historical['stale']
    with pytest.raises(ReviewConflict, match='fresh evidence'):
        decide(lib, target, historical, 'accept')
    decide(lib, target, historical, 'restore')
    assert items(lib, target)[0]['stale']
    with pytest.raises(ReviewConflict, match='fresh evidence'):
        decide(lib, target, historical, 'accept')


def test_stale_and_concurrent_decisions_preserve_drafts(review_book):
    lib, _, hit, _ = review_book
    target = hit['section_id']
    initial = offer(lib, target)
    item = items(lib, target)[0]
    decide(lib, target, item, 'reject')
    with pytest.raises(ReviewConflict, match='another tab'):
        lib.decide_review(target, item['id'], 'accept', revision=initial['revision'], expected_version=initial['version'])
    lib.annotate(target, {'field': 'title', 'value': 'Intervening title', 'origin': 'user', 'status': 'confirmed', 'evidence': 'Other tab.'})
    with pytest.raises(ReviewConflict, match='Current information changed'):
        decide(lib, target, item, 'accept')
    assert items(lib, target)[0]['status'] == 'rejected'


def test_old_drafts_load_without_writes(review_book):
    lib, _, hit, _ = review_book
    target = hit['section_id']
    offer(lib, target)
    path = lib.state / 'reviews' / (target + '.json')
    old = read_json(path, {})
    old.pop('decisions')
    atomic_json(path, old)
    before = path.read_bytes()
    assert lib.review_draft(target)['decisions'] == {}
    assert items(lib, target)[0]['status'] == 'pending'
    assert path.read_bytes() == before


def test_receipt_recovery_marks_accepted_item_saved(review_book, monkeypatch):
    from book_library import review
    lib, _, hit, _ = review_book
    target = hit['section_id']
    offer(lib, target)
    saved = decide(lib, target, items(lib, target)[0], 'accept')
    real_write = review.atomic_json
    monkeypatch.setattr(review, 'atomic_json', lambda *a: (_ for _ in ()).throw(OSError('After curation commit')))
    with pytest.raises(OSError):
        apply(lib, target, saved)
    count = len(lib._curation())
    monkeypatch.setattr(review, 'atomic_json', real_write)
    assert apply(lib, target, saved)['duplicate']
    assert len(lib._curation()) == count
    assert items(lib, target)[0]['status'] == 'saved'
    decide(lib, target, items(lib, target)[0], 'restore')
    assert len(lib._curation()) == count
