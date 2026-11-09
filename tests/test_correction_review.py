"""A draft is not curation; reviewed saves preserve scope and provenance."""
from __future__ import annotations

import copy

import pytest

from book_library.review import ReviewConflict, parse_field_value
from book_library.service import Library
from book_library.storage import atomic_json
from test_service import docx, seed


@pytest.fixture
def review_book(tmp_path):
    root = tmp_path / 'books'
    source = docx(root / 'Collection' / 'Collection.docx', [
        ('Heading1', 'Publication details'), 'A Collection', 'Edited by Jane Doe',
        'Example Press, 2014',
        ('Heading1', 'Introduction'), 'Amber lanterns introduce the general collection.',
        ('Heading1', 'Midweek services'), 'This grouping concerns shared worship.',
        ('Heading1', 'Introduction'), 'Violet rivers introduce the midweek services.',
        'A prayer follows, then a separate reflection.',
    ])
    lib = seed(root, [{'title': 'A Collection', 'author': 'Jane Doe, editor', 'paths': [source],
                       'metadata': {'publisher': 'Example Press', 'publication_year': 2014}}])
    general = lib.search('amber lanterns', engine='exact')['direct'][0]
    midweek = lib.search('violet rivers', engine='exact')['direct'][0]
    return lib, source, general, midweek


def fields(context):
    return {field['key']: field for field in context['fields']}


def change(value, evidence='Inspected the exact source heading.', verified=False):
    return {'value': value, 'evidence': evidence, 'verified': verified}


def draft(lib, target, changes):
    context = lib.review_context(target)
    previous = lib.review_draft(target)
    return lib.save_review_draft(target, changes, revision=context['revision'], expected_version=previous['version'])


def apply(lib, target, saved, selected=None, request='save-1', **kwargs):
    return lib.apply_review(target, selected if selected is not None else list(saved['changes']),
                            revision=saved['revision'], expected_version=saved['version'],
                            request_id=request, **kwargs)


def test_context_distinguishes_repeated_titles_and_current_provenance(review_book):
    lib, _, general, midweek = review_book
    a, b = [lib.review_context(hit['section_id']) for hit in (general, midweek)]
    assert a['target']['title'] == b['target']['title'] == 'Introduction'
    assert a['target']['id'] != b['target']['id']
    assert a['target']['location'] != b['target']['location']
    assert 'Amber' in ' '.join(e['text'] for e in a['evidence'] if e['in_target'])
    assert 'Violet' in ' '.join(e['text'] for e in b['evidence'] if e['in_target'])
    assert a['target']['read_url'].startswith('/units/')
    assert a['coverage_complete']
    assert not a['boundary_risk']
    lib.annotate(general['section_id'], {'field': 'profile', 'value': {'subjects': ['worship']},
        'origin': 'user', 'status': 'confirmed', 'evidence': 'Only the general introduction was checked.'})
    updated = fields(lib.review_context(general['section_id']))
    assert updated['profile.subjects']['value'] == ['worship']
    assert updated['profile.subjects']['origin'] == 'user'
    assert updated['profile.subjects']['status'] == 'confirmed'
    assert updated['profile.subjects']['evidence'] == 'Only the general introduction was checked.'
    assert not updated['bibliography.publisher']['editable']
    assert updated['bibliography.publisher']['edit_url'].endswith(general['work_id'])


def test_drafts_persist_separately_and_ai_merge_preserves_manual_work(review_book):
    lib, _, general, _ = review_book
    target = general['section_id']
    before = copy.deepcopy(lib._curation())
    saved = draft(lib, target, {'title': change('General introduction', evidence='')})
    reopened = Library(lib.root).review_draft(target)
    assert reopened['changes'] == saved['changes']
    assert lib._curation() == before
    lib.store_review_suggestions(target, {'suggestions': [{'id': 'p1', 'field': 'bibliography.title',
        'value': 'Introduction', 'rationale': 'Printed heading.', 'evidence': []}], 'unresolved': ['Author not identified.'],
        'status': 'complete', 'external_report': {'text': 'A cited report.', 'sources': []}}, revision=saved['revision'])
    merged = lib.review_draft(target)
    assert merged['changes'] == saved['changes']
    assert merged['suggestions'][0]['field'] == 'bibliography.title'
    assert merged['external_report']['text'] == 'A cited report.'
    assert lib._curation() == before


def test_selective_citation_save_and_independent_verification(review_book, monkeypatch):
    lib, _, general, _ = review_book
    target = general['section_id']
    monkeypatch.setattr(lib, 'sync', lambda: pytest.fail('Citation-only edits must not rebuild'))
    saved = draft(lib, target, {'bibliography.title': change('An Introduction'),
                                'bibliography.authors': change([{'literal': 'Jane Doe'}], verified=True)})
    result = apply(lib, target, saved, ['bibliography.title'])
    assert result['saved'] and not result['refresh_required']
    events = [e for e in lib._curation() if e.get('review_request_id') == 'save-1']
    assert len(events) == 1 and events[0]['status'] == 'provisional'
    assert events[0]['value'] == {'title': 'An Introduction'}
    remaining = lib.review_draft(target)
    assert set(remaining['changes']) == {'bibliography.authors'}
    apply(lib, target, remaining, request='save-2')
    record = fields(lib.review_context(target))
    assert record['bibliography.title']['status'] == 'provisional'
    assert record['bibliography.authors']['status'] == 'confirmed'
    citation = lib.cite(general['id'])
    assert not citation['ready']
    assert 'title' in citation['review_fields'] or 'section.title' in citation['review_fields']


def test_all_fields_validated_before_atomic_apply(review_book):
    lib, _, general, _ = review_book
    target = general['section_id']
    saved = draft(lib, target, {'bibliography.title': change('New title'),
                                'bibliography.authors': change([{'literal': 'Jane Doe'}], evidence='')})
    before = copy.deepcopy(lib._curation())
    with pytest.raises(ValueError, match='evidence'):
        apply(lib, target, saved)
    assert lib._curation() == before
    assert lib.review_draft(target)['changes'] == saved['changes']


def test_duplicate_save_is_idempotent_before_version_check(review_book):
    lib, _, general, _ = review_book
    target = general['section_id']
    saved = draft(lib, target, {'bibliography.title': change('New title')})
    apply(lib, target, saved)
    count = len(lib._curation())
    repeated = apply(lib, target, saved)
    assert repeated['duplicate'] and len(lib._curation()) == count


def test_old_tab_cannot_overwrite_newer_draft_or_discard(review_book):
    lib, _, general, _ = review_book
    target = general['section_id']
    first = draft(lib, target, {'title': change('First')})
    second = lib.save_review_draft(target, {'title': change('Second')}, revision=first['revision'], expected_version=first['version'])
    with pytest.raises(ReviewConflict, match='another tab'):
        lib.save_review_draft(target, {'title': change('Stale')}, revision=first['revision'], expected_version=first['version'])
    with pytest.raises(ReviewConflict):
        lib.discard_review_draft(target, expected_version=first['version'])
    assert lib.review_draft(target)['changes'] == second['changes']


def test_intervening_curation_requires_recheck_and_clears_verification(review_book):
    lib, _, general, _ = review_book
    target = general['section_id']
    saved = draft(lib, target, {'bibliography.title': change('Draft title', verified=True)})
    lib.annotate(target, {'field': 'bibliography', 'value': {'title': 'Another title'},
                         'origin': 'user', 'status': 'confirmed', 'evidence': 'Another editor checked the source.'})
    with pytest.raises(ReviewConflict, match='Current information changed'):
        apply(lib, target, saved)
    assert lib.review_draft(target)['stale']
    rebased = lib.rebase_review_draft(target, expected_version=saved['version'])
    assert not rebased['stale'] and not rebased['changes']['bibliography.title']['verified']
    assert rebased['changes']['bibliography.title']['value'] == 'Draft title'


def test_changed_original_withholds_stale_evidence_and_blocks_apply(review_book):
    lib, source, general, _ = review_book
    target = general['section_id']
    saved = draft(lib, target, {'bibliography.title': change('Draft title')})
    docx(source, [('Heading1', 'Introduction'), 'Changed source text.'])
    context = lib.review_context(target)
    assert not context['source_current'] and context['evidence'] == []
    with pytest.raises(ReviewConflict, match='source has changed'):
        apply(lib, target, saved)
    assert lib.review_draft(target)['changes'] == saved['changes']


def test_names_round_trip_preserves_structured_components_and_unknown_absent(review_book):
    lib, _, general, _ = review_book
    target = general['section_id']
    names = [{'given': 'Jane', 'family': 'Doe', 'suffix': 'Jr.', 'short': 'Doe'}]
    lib.annotate(target, {'field': 'bibliography', 'value': {'authors': names},
                         'origin': 'user', 'status': 'confirmed', 'evidence': 'Printed byline checked.'})
    field = fields(lib.review_context(target))['bibliography.authors']
    assert parse_field_value(field, 'Jane Doe, Jr.', mode='names', short_names='Doe') == names
    assert parse_field_value(field, '', mode='unknown') is None
    assert parse_field_value(field, '', mode='absent') == []
    with pytest.raises(ValueError, match='Clear the names'):
        parse_field_value(field, 'Jane Doe', mode='absent')


def test_translator_inheritance_and_explicit_empty_are_distinct(review_book):
    lib, _, general, _ = review_book
    lib.annotate(general['work_id'], {'field': 'bibliography', 'value': {'translators': [{'literal': 'Translator Name'}]},
        'origin': 'user', 'status': 'confirmed', 'evidence': 'Title page translation credit.'})
    target = general['section_id']
    field = fields(lib.review_context(target))['bibliography.translators']
    assert field['inherited'] and field['raw_value'] is None
    assert field['value'] == [{'literal': 'Translator Name'}]
    assert parse_field_value(field, '', mode='inherit') is None
    assert parse_field_value(field, '', mode='absent') == []
    saved = draft(lib, target, {'bibliography.translators': change([], verified=True)})
    apply(lib, target, saved)
    field = fields(lib.review_context(target))['bibliography.translators']
    assert field['value'] == [] and not field['inherited']


def test_manual_batch_refreshes_once_and_user_corrections_survive_rebuild(review_book, monkeypatch):
    lib, _, general, _ = review_book
    target = general['work_id']
    actual_sync = lib.sync
    calls = []
    def sync():
        calls.append(True)
        return actual_sync(semantic=False)
    monkeypatch.setattr(lib, 'sync', sync)
    saved = draft(lib, target, {'title': change('My collection'), 'profile.subjects': change(['worship'])})
    result = apply(lib, target, saved)
    assert result['refresh_required'] and len(calls) == 1
    lib.annotate(target, {'field': 'title', 'value': 'Generated overwrite', 'origin': 'codex',
                         'status': 'confirmed', 'evidence': 'Generated candidate.'})
    actual_sync(rebuild=True, semantic=False)
    assert lib.book(target)['title'] == 'My collection'
    assert lib.book(target)['profile']['subjects'] == ['worship']


def test_noop_does_not_reverify_but_explicit_verification_does(review_book):
    lib, _, general, _ = review_book
    target = general['work_id']
    lib.annotate(target, {'field': 'bibliography', 'value': {'title': 'A Collection'},
                         'origin': 'user', 'status': 'provisional', 'evidence': 'A saved title.'})
    field = fields(lib.review_context(target))['bibliography.title']
    before = len(lib._curation())
    saved = draft(lib, target, {'bibliography.title': change(field['value'], evidence='')})
    result = apply(lib, target, saved)
    assert result['unchanged'] and len(lib._curation()) == before
    saved = draft(lib, target, {'bibliography.title': change(field['value'], verified=True)})
    apply(lib, target, saved, request='save-2')
    assert fields(lib.review_context(target))['bibliography.title']['status'] == 'confirmed'


def test_final_evidence_edit_is_allowed_but_unsaved_value_is_rejected(review_book):
    lib, _, general, _ = review_book
    target = general['section_id']
    saved = draft(lib, target, {'bibliography.title': change('New title', evidence='')})
    changed = copy.deepcopy(saved['changes'])
    changed['bibliography.title'].update(evidence='Verified printed title.', verified=True)
    wrong = copy.deepcopy(changed)
    wrong['bibliography.title']['value'] = 'Unsaved text'
    with pytest.raises(ReviewConflict, match='Save edited values'):
        apply(lib, target, saved, changes=wrong)
    apply(lib, target, saved, changes=changed)
    assert fields(lib.review_context(target))['bibliography.title']['status'] == 'confirmed'


def test_atomic_write_failure_leaves_history_and_draft_intact(review_book, monkeypatch):
    from book_library import review
    lib, _, general, _ = review_book
    target = general['section_id']
    saved = draft(lib, target, {'bibliography.title': change('New title'),
                                'bibliography.authors': change([{'literal': 'Jane Doe'}])})
    before = copy.deepcopy(lib._curation())
    def fail(*args):
        raise OSError('Synthetic failed batch write.')
    monkeypatch.setattr(review, 'append_jsonl_batch', fail)
    with pytest.raises(OSError):
        apply(lib, target, saved)
    assert lib._curation() == before
    assert lib.review_draft(target)['changes'] == saved['changes']


def test_catalog_candidate_can_be_adopted_as_provisional_and_null_stays_unknown(review_book):
    lib, _, general, _ = review_book
    target = general['work_id']
    field = fields(lib.review_context(target))['bibliography.title']
    assert field['status'] == 'candidate'
    saved = draft(lib, target, {'bibliography.title': change(field['value'], evidence='Catalog title retained pending source review.')})
    apply(lib, target, saved)
    field = fields(lib.review_context(target))['bibliography.title']
    assert field['status'] == 'provisional' and field['origin'] == 'user'
    saved = draft(lib, target, {'bibliography.title': change(None, evidence='The correct title remains unknown.')})
    apply(lib, target, saved, request='save-2')
    field = fields(lib.review_context(target))['bibliography.title']
    assert field['value'] is None and field['raw_value'] is None


def test_reordered_names_preserve_components_and_edit_short_names(review_book):
    lib, _, general, _ = review_book
    target = general['section_id']
    names = [{'given': 'Jane', 'family': 'Doe', 'suffix': 'Jr.', 'short': 'Doe'},
             {'given': 'John', 'family': 'Smith', 'short': 'Smith'}]
    lib.annotate(target, {'field': 'bibliography', 'value': {'authors': names},
        'origin': 'user', 'status': 'confirmed', 'evidence': 'Bylines inspected.'})
    field = fields(lib.review_context(target))['bibliography.authors']
    reordered = parse_field_value(field, 'John Smith\nJane Doe, Jr.', mode='names', short_names='J. Smith\nDoe')
    assert reordered[0] == {**names[1], 'short': 'J. Smith'}
    assert reordered[1] == names[0]


def test_replay_recovers_receipt_after_interrupted_draft_write(review_book, monkeypatch):
    from book_library import review
    lib, _, general, _ = review_book
    target = general['section_id']
    saved = draft(lib, target, {'bibliography.title': change('Durable title')})
    actual_atomic_json = review.atomic_json
    def fail(*args):
        raise OSError('Interrupted after curation commit.')
    monkeypatch.setattr(review, 'atomic_json', fail)
    with pytest.raises(OSError):
        apply(lib, target, saved)
    count = len(lib._curation())
    monkeypatch.setattr(review, 'atomic_json', actual_atomic_json)
    recovered = apply(lib, target, saved)
    assert recovered['duplicate'] and recovered['saved']
    assert len(lib._curation()) == count
    assert lib.review_draft(target)['changes'] == {}


def test_empty_facets_are_unknown_and_have_specific_explanations(review_book):
    lib, _, general, _ = review_book
    context = fields(lib.review_context(general['section_id']))
    assert 'Methods of interpretation' in context['profile.approaches']['help']
    assert 'Recurring images' in context['profile.motifs']['help']
    assert 'Other named books' in context['profile.works']['help']
    assert 'incidental quotation' in context['profile.biblical_references']['help']
    assert context['profile.themes']['example'] != context['profile.subjects']['example']
    for name in ('approaches', 'motifs', 'works'):
        field = context['profile.' + name]
        assert field['value'] == [] and field['status'] == 'unknown' and field['origin'] == 'not_recorded'
    saved = draft(lib, general['section_id'], {'profile.motifs': change([], verified=True)})
    apply(lib, general['section_id'], saved)
    field = fields(lib.review_context(general['section_id']))['profile.motifs']
    assert field['value'] == [] and field['status'] == 'confirmed' and field['origin'] == 'user'


def test_explicit_unknowns_do_not_resurrect_catalog_identifiers_for_ai(review_book):
    lib, _, general, _ = review_book
    lib.annotate(general['work_id'], {'field': 'bibliography',
        'value': {'publisher': None, 'year': None, 'edition': None},
        'origin': 'user', 'status': 'confirmed', 'evidence': 'These catalog claims belong to a different edition.'})
    for target in (general['work_id'], general['section_id'], general['id']):
        context = lib.review_context(target)
        for key in ('publisher', 'year', 'edition'):
            assert context['book_identifiers'][key] is None
            assert context['target']['bibliography'][key] is None
            assert fields(context)['bibliography.' + key]['value'] is None
        assert context['target']['publisher'] is None
        assert context['target']['edition'] is None


def test_passage_derived_credit_reports_its_actual_scope(review_book):
    lib, _, general, _ = review_book
    lib.annotate(general['section_id'], {'field': 'bibliography',
        'value': {'authors': [{'literal': 'Section Writer'}], 'type': 'chapter'},
        'origin': 'user', 'status': 'confirmed', 'evidence': 'Section credit.'})
    lib.annotate(general['section_id'], {'field': 'text_type', 'value': 'commentary',
        'origin': 'user', 'status': 'confirmed', 'evidence': 'Section type inspected.'})
    lib.sync(semantic=False)
    before = fields(lib.review_context(general['id']))
    assert before['bibliography.authors']['inherited']
    assert before['bibliography.type']['inherited']
    assert before['text_type']['inherited']
    lib.annotate(general['id'], {'field': 'bibliography',
        'value': {'authors': [{'literal': 'Passage Writer'}]},
        'origin': 'user', 'status': 'confirmed', 'evidence': 'This passage has its own byline.'})
    after = fields(lib.review_context(general['id']))
    assert after['attribution']['value'] == 'Passage Writer'
    assert after['attribution']['provenance_target_id'] == general['id']
    assert not after['attribution']['inherited']
    assert not after['bibliography.authors']['inherited']


def test_complete_mixed_component_target_still_has_boundary_warning(tmp_path):
    from test_scripture_citations import segmented_source
    lib, hit, _ = segmented_source(tmp_path)
    lib.sync(semantic=False)
    context = lib.review_context(hit['id'])
    assert context['coverage_complete']
    assert context['boundary_risk']
