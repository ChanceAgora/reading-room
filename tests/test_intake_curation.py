"""Automatic changes require stronger evidence than reviewable suggestions."""
import copy
import json

import pytest

from book_library.intake_curation import apply_automatic, automatic_changes, undo_automatic
from book_library.review import ReviewConflict
from test_service import docx, seed


@pytest.fixture
def intake_book(tmp_path):
    root = tmp_path / 'books'
    source = docx(root / 'Collection' / 'book.docx', [
        ('Heading1', 'Publication'), 'A Collection', 'Published by Example Press',
        'Publication year: 2026', 'First edition',
        ('Heading1', 'Introduction'), 'Written by Jane Doe',
        'This book explains the purpose and arrangement of the collection for readers interested in worship.',
        ('Heading1', 'Translation'), 'Translated by Alex Reader',
        'These paragraphs introduce the purpose and arrangement of another part of this book for its readers.',
        ('Heading1', 'Roster'), 'Jane Doe, John Roe, and many other contributors.',
    ])
    lib = seed(root, [{'title': 'A Collection', 'author': 'Unknown', 'paths': [source]}])
    hit = lib.search('interested in worship', engine='exact')['direct'][0]
    translation = lib.search('another part', engine='exact')['direct'][0]
    return lib, source, hit, translation


def proposal(context, key, value, text, **extra):
    evidence = next(source for source in context['evidence'] if text in source['text'])
    return {'field': key, 'value': value, 'strength': 'well_supported', 'model_strength': 'well_supported',
            'rationale': 'The inspected source supports this value.', 'scope_supported': True,
            'coverage_complete': context['coverage_complete'], 'relationship': 'source_heading',
            'evidence': [{'source_id': evidence['id'], 'quote': text, 'read_url': evidence['read_url']}], **extra}


def apply(lib, target, proposals, request='once', **extra):
    context = lib.review_context(target)
    return apply_automatic(lib, target, {'suggestions': proposals, 'unresolved': [], **extra},
                           intake_id='intake_fixture', request_id=request, revision=context['revision'])


def field(lib, target, key):
    return next(f for f in lib.review_context(target)['fields'] if f['key'] == key)


def test_scoped_title_and_classification_are_provisional_and_idempotent(intake_book):
    lib, _, hit, _ = intake_book
    target = hit['section_id']; context = lib.review_context(target)
    title = proposal(context, 'bibliography.title', 'Introduction', 'Introduction')
    category = proposal(context, 'text_type', 'editorial', 'This book explains the purpose and arrangement of the collection for readers interested in worship.', relationship='subject_classification')
    result = apply(lib, target, [title, category])
    assert result['fields'] == ['bibliography.title', 'text_type']
    assert result['refresh_required']
    assert all(event['origin'] == 'codex' and event['status'] == 'provisional' for event in lib._curation())
    assert not lib.review_draft(target)['changes']
    assert not lib.review_draft(target)['decisions']
    replay = apply_automatic(lib, target, {'suggestions': [title, category]}, intake_id='intake_fixture',
                             request_id='once', revision=context['revision'])
    assert replay['replay'] and len(lib._curation()) == 2


@pytest.mark.parametrize('kind', ['title', 'year', 'roster', 'label', 'missing_strength'])
def test_confidence_and_real_quote_alone_do_not_authorize_change(intake_book, kind):
    lib, _, hit, _ = intake_book
    target = hit['work_id'] if kind == 'year' else hit['section_id']
    context = lib.review_context(target)
    if kind == 'title':
        p = proposal(context, 'bibliography.title', 'Invented title', 'Introduction')
    elif kind == 'year':
        p = proposal(context, 'bibliography.year', '2025', 'Publication year: 2026', relationship='publication_fact')
    elif kind == 'roster':
        p = proposal(context, 'bibliography.authors', [{'literal': 'John Roe'}], 'Introduction', relationship='direct_credit')
    elif kind == 'label':
        p = proposal(context, 'profile.subjects', ['neuroscience'], 'Introduction', relationship='subject_classification')
    else:
        p = proposal(context, 'bibliography.title', 'Introduction', 'Introduction')
        p.pop('strength'); p.pop('model_strength')
    result = apply(lib, target, [p])
    assert result['blocked'] and not result['saved']
    assert not lib._curation()


def test_explicit_publication_assertions_and_target_labels(intake_book):
    lib, _, hit, _ = intake_book
    context = lib.review_context(hit['work_id'])
    result = apply(lib, hit['work_id'], [
        proposal(context, 'bibliography.publisher', 'Example Press', 'Published by Example Press', relationship='publication_fact'),
        proposal(context, 'bibliography.year', '2026', 'Publication year: 2026', relationship='publication_fact'),
        proposal(context, 'bibliography.edition', 'First edition', 'First edition', relationship='publication_fact'),
    ])
    assert result['fields'] == ['bibliography.publisher', 'bibliography.year', 'bibliography.edition']
    assert not result['refresh_required']
    context = lib.review_context(hit['section_id'])
    p = proposal(context, 'profile.subjects', ['worship'], 'This book explains the purpose and arrangement of the collection for readers interested in worship.', relationship='subject_classification')
    assert apply(lib, hit['section_id'], [p], request='labels')['fields'] == ['profile.subjects']


@pytest.mark.parametrize('key,value,statements', [
    ('year', '2015', ['First published in 2015', 'This edition published in 2026']),
    ('publisher', 'First Press', ['Published by First Press', 'Published by Second Press']),
    ('edition', 'First edition', ['First edition', 'Second edition']),
])
def test_conflicting_actual_copy_publication_assertions_need_review(tmp_path, key, value, statements):
    root = tmp_path / 'books'
    source = docx(root / 'Edition' / 'book.docx', [
        ('Heading1', 'Publication'), 'An Edition', *statements,
        ('Heading1', 'Introduction'), 'This introduction explains the purpose of the book.',
    ])
    lib = seed(root, [{'title': 'An Edition', 'author': 'Unknown', 'paths': [source]}])
    target = lib.search('purpose of the book', engine='exact')['direct'][0]['work_id']
    context = lib.review_context(target)
    p = proposal(context, 'bibliography.' + key, value, statements[0], relationship='publication_fact')
    result = apply(lib, target, [p])
    assert not result['saved'] and result['needs_review']
    assert not lib._curation()


def test_byline_credit_preserves_printed_name_without_guessing_name_parts(intake_book):
    lib, _, hit, _ = intake_book
    context = lib.review_context(hit['section_id'])
    p = proposal(context, 'bibliography.authors', [{'given': 'Jane', 'family': 'Doe'}], 'Written by Jane Doe', relationship='direct_credit')
    result = apply(lib, hit['section_id'], [p])
    assert result['fields'] == ['bibliography.authors']
    assert field(lib, hit['section_id'], 'bibliography.authors')['value'] == [{'literal': 'Jane Doe'}]


def test_undo_suppresses_equivalent_literal_and_structured_name(intake_book):
    lib, _, hit, _ = intake_book; target = hit['section_id']; context = lib.review_context(target)
    p = proposal(context, 'bibliography.authors', [{'literal': 'Jane Doe'}], 'Written by Jane Doe', relationship='direct_credit')
    assert apply(lib, target, [p])['saved']
    undo_automatic(lib, 'intake_fixture')
    p = proposal(lib.review_context(target), 'bibliography.authors', [{'given': 'Jane', 'family': 'Doe'}], 'Written by Jane Doe', relationship='direct_credit')
    result = apply(lib, target, [p], request='different-shape')
    assert not result['saved'] and 'undone' in result['blocked'][0]['reason']


def test_classification_does_not_reuse_contributor_boundary_gate(intake_book):
    lib, _, hit, _ = intake_book; target = hit['section_id']
    lib.annotate(target, {'field': 'text_type', 'value': 'mixed', 'origin': 'codex', 'status': 'provisional', 'evidence': 'Earlier heuristic.'})
    lib.sync(semantic=False)
    context = lib.review_context(target)
    assert context['boundary_risk'] and context['coverage_complete']
    p = proposal(context, 'text_type', 'editorial', 'This book explains the purpose and arrangement of the collection for readers interested in worship.', relationship='subject_classification')
    credit = proposal(context, 'bibliography.authors', [{'literal': 'Jane Doe'}], 'Written by Jane Doe', relationship='direct_credit')
    result = apply(lib, target, [p, credit])
    assert result['fields'] == ['text_type']
    assert result['blocked'][0]['field'] == 'bibliography.authors'


def test_mixed_judgment_requires_distinct_supported_kinds_without_full_coverage():
    from book_library.intake_curation import _support_rule
    sources = [{'id': 'poem', 'text': 'A silver leaf\nUpon the stream\nBecomes a star', 'kind': 'poetry', 'in_target': True},
               {'id': 'comment', 'text': 'This commentary explains the meaning of the passage.', 'kind': 'paragraph', 'in_target': True}]
    context = {'target': {'scope': 'section'}, 'evidence': sources, 'coverage_complete': False, 'boundary_risk': True}
    p = {'field': 'text_type', 'value': 'mixed', 'relationship': 'subject_classification', 'coverage_complete': False,
         'content_kinds': ['poetry', 'commentary'], 'evidence': [{'source_id': source['id'], 'quote': source['text']} for source in sources]}
    assert _support_rule(context, p, {})[0] == 'supported_mixed_judgment'
    p['value'] = 'commentary'
    assert _support_rule(context, p, {})[0] is None
    p.update(value='mixed', content_kinds=['prose', 'commentary'])
    assert _support_rule(context, p, {})[0] is None


@pytest.mark.parametrize('protection', ['user', 'confirmed', 'manual', 'decision', 'conflict', 'incomplete'])
def test_existing_work_and_uncertainty_protected(intake_book, protection):
    lib, _, hit, _ = intake_book; target = hit['section_id']
    context = lib.review_context(target)
    p = proposal(context, 'bibliography.title', 'Introduction', 'Introduction')
    if protection in ('user', 'confirmed'):
        lib.annotate(target, {'field': 'bibliography', 'value': {'title': 'My title'},
                             'origin': 'user' if protection == 'user' else 'codex',
                             'status': 'confirmed' if protection == 'confirmed' else 'provisional', 'evidence': 'Existing work.'})
    elif protection == 'manual':
        lib.save_review_draft(target, {'bibliography.title': {'value': 'My draft', 'evidence': 'My work.', 'verified': False}},
                              revision=context['revision'], expected_version=0)
    elif protection == 'decision':
        d = lib.store_review_suggestions(target, {'suggestions': [p]}, revision=context['revision'])
        from book_library.review_items import review_items
        item = review_items(context, d)[0]
        lib.decide_review(target, item['id'], 'reject', revision=context['revision'], expected_version=d['version'])
    elif protection == 'incomplete':
        p['scope_supported'] = False
    kwargs = {'unresolved': [{'field': 'bibliography.title', 'reason': 'Conflicting title.'}]} if protection == 'conflict' else {}
    before = copy.deepcopy(lib._curation())
    result = apply(lib, target, [p], **kwargs)
    assert not result['saved'] and result['blocked']
    assert lib._curation() == before


def test_stale_and_forged_local_quote_rejected(intake_book):
    lib, _, hit, _ = intake_book; target = hit['section_id']
    context = lib.review_context(target)
    p = proposal(context, 'bibliography.title', 'Introduction', 'Introduction')
    with pytest.raises(ReviewConflict):
        apply_automatic(lib, target, {'suggestions': [p]}, intake_id='intake_fixture', request_id='stale', revision='obsolete')
    p['evidence'][0]['quote'] = 'Invented quotation'
    assert not apply(lib, target, [p])['saved']


def test_undo_restores_absence_and_suppresses_reapplication(intake_book):
    lib, _, hit, _ = intake_book; target = hit['section_id']
    context = lib.review_context(target)
    p = proposal(context, 'bibliography.title', 'Introduction', 'Introduction')
    result = apply(lib, target, [p])
    assert field(lib, target, 'bibliography.title')['value'] == 'Introduction'
    reversal = undo_automatic(lib, 'intake_fixture')
    assert reversal['undone'] == [result['applied'][0]['event_id']]
    assert field(lib, target, 'bibliography.title')['value'] is None
    assert field(lib, target, 'bibliography.title')['origin'] == 'not_recorded'
    assert automatic_changes(lib, 'intake_fixture')[0]['undone']
    assert not apply(lib, target, [p], request='again')['saved']
    assert undo_automatic(lib, 'intake_fixture')['undone'] == []
    lib.sync(semantic=False)
    assert field(lib, target, 'bibliography.title')['value'] is None


def test_undo_restores_inherited_translator(intake_book):
    lib, _, hit, translation = intake_book
    lib.annotate(hit['work_id'], {'field': 'bibliography', 'value': {'translators': [{'literal': 'Original Translator'}]},
                                 'origin': 'codex', 'status': 'provisional', 'evidence': 'Earlier source evidence.'})
    target = translation['section_id']; context = lib.review_context(target)
    assert field(lib, target, 'bibliography.translators')['inherited']
    p = proposal(context, 'bibliography.translators', [{'literal': 'Alex Reader'}], 'Translated by Alex Reader', relationship='direct_credit')
    assert apply(lib, target, [p])['saved']
    undo_automatic(lib, 'intake_fixture')
    restored = field(lib, target, 'bibliography.translators')
    assert restored['inherited'] and restored['value'] == [{'literal': 'Original Translator'}]


def test_bulk_undo_preserves_later_edits(intake_book):
    lib, _, hit, _ = intake_book; target = hit['section_id']; context = lib.review_context(target)
    p = proposal(context, 'bibliography.title', 'Introduction', 'Introduction')
    apply(lib, target, [p])
    lib.annotate(target, {'field': 'bibliography', 'value': {'title': 'My later title'}, 'origin': 'user', 'status': 'confirmed', 'evidence': 'My review.'})
    result = undo_automatic(lib, 'intake_fixture')
    assert result['skipped'] and not result['undone']
    assert field(lib, target, 'bibliography.title')['value'] == 'My later title'


def test_bulk_undo_removes_same_intake_change_chain_in_one_action(intake_book):
    lib, _, hit, _ = intake_book; target = hit['section_id']
    text = 'This book explains the purpose and arrangement of the collection for readers interested in worship.'
    first = proposal(lib.review_context(target), 'profile.subjects', ['worship'], text, relationship='subject_classification')
    apply(lib, target, [first])
    second = proposal(lib.review_context(target), 'profile.subjects', ['worship', 'purpose'], text, relationship='subject_classification')
    apply(lib, target, [second], request='second')
    result = undo_automatic(lib, 'intake_fixture')
    assert len(result['undone']) == 2
    assert field(lib, target, 'profile.subjects')['value'] == []


def test_interrupted_undo_retains_refresh_obligation(intake_book, monkeypatch):
    import book_library.intake_curation as curation
    from book_library.intake import _load, _path
    from book_library.storage import atomic_json
    lib, _, hit, _ = intake_book; target = hit['section_id']
    text = 'This book explains the purpose and arrangement of the collection for readers interested in worship.'
    p = proposal(lib.review_context(target), 'text_type', 'editorial', text, relationship='subject_classification')
    apply(lib, target, [p])
    atomic_json(_path(lib, 'intake_fixture'), {'id': 'intake_fixture', 'version': 1, 'refresh_pending': False})
    append = curation.append_jsonl_batch
    def interrupted_append(path, records):
        append(path, records)
        raise OSError('Interrupted immediately after committing Undo')
    monkeypatch.setattr(curation, 'append_jsonl_batch', interrupted_append)
    with pytest.raises(OSError):
        undo_automatic(lib, 'intake_fixture', expected_version=1)
    assert _load(lib, 'intake_fixture')['refresh_pending']
    assert automatic_changes(lib, 'intake_fixture')[0]['undone']
    monkeypatch.setattr(curation, 'append_jsonl_batch', append)
    assert not undo_automatic(lib, 'intake_fixture', expected_version=2)['undone']
    assert _load(lib, 'intake_fixture')['refresh_pending']


def test_commit_receipt_recovered_after_interrupted_journal_write(intake_book, monkeypatch):
    import book_library.intake_curation as curation
    lib, _, hit, _ = intake_book; target = hit['section_id']; context = lib.review_context(target)
    p = proposal(context, 'bibliography.title', 'Introduction', 'Introduction')
    original = curation.atomic_json
    monkeypatch.setattr(curation, 'atomic_json', lambda *args: (_ for _ in ()).throw(OSError('interrupted')))
    with pytest.raises(OSError):
        apply(lib, target, [p])
    monkeypatch.setattr(curation, 'atomic_json', original)
    receipt = apply_automatic(lib, target, {'suggestions': [p]}, intake_id='intake_fixture', request_id='once', revision=context['revision'])
    assert receipt['replay'] and len(lib._curation()) == 1


def test_commit_recovery_retains_blocked_findings(intake_book, monkeypatch):
    import book_library.intake_curation as curation
    lib, _, hit, _ = intake_book; target = hit['section_id']; context = lib.review_context(target)
    valid = proposal(context, 'bibliography.title', 'Introduction', 'Introduction')
    invalid = proposal(context, 'profile.subjects', ['neuroscience'], 'Introduction', relationship='subject_classification')
    original = curation.atomic_json
    monkeypatch.setattr(curation, 'atomic_json', lambda *args: (_ for _ in ()).throw(OSError('interrupted')))
    with pytest.raises(OSError):
        apply(lib, target, [valid, invalid])
    monkeypatch.setattr(curation, 'atomic_json', original)
    receipt = apply_automatic(lib, target, {'suggestions': [valid, invalid]}, intake_id='intake_fixture', request_id='once', revision=context['revision'])
    assert receipt['replay'] and receipt['needs_review']
    assert receipt['blocked'][0]['field'] == 'profile.subjects'


def test_external_fact_must_equal_same_record_and_value(intake_book):
    lib, _, hit, _ = intake_book; target = hit['work_id']; context = lib.review_context(target)
    # A typed, superficially strong proposal is still not a source-bound fact.
    p = {'field': 'bibliography.year', 'value': '2025', 'strength': 'well_supported',
         'rationale': 'A returned source was checked.', 'scope_supported': True, 'edition_match': True,
         'evidence': [{'source_id': 'external_record', 'url': 'https://loc.gov/item/book/', 'summary': 'Year 2025.'}],
         'reported_facts': [{'source_id': 'external_record', 'kind': 'year', 'value': '2015'}]}
    result = apply(lib, target, [p], external_report={'sources': [{'id': 'external_record', 'url': 'https://loc.gov/item/book/', 'cited_report_text': 'Published in 2015.'}]})
    assert not result['saved']


def test_unresolved_identifier_relationship_blocks_publication_changes(intake_book):
    lib, _, hit, _ = intake_book; target = hit['work_id']; context = lib.review_context(target)
    p = proposal(context, 'bibliography.year', '2026', 'Publication year: 2026', relationship='publication_fact')
    result = apply(lib, target, [p], assessments=[{'kind': 'edition', 'edition_relationship': 'unknown',
                                                'comparison': {'compared_isbn': '9780664259648'}}])
    assert not result['saved'] and 'identifiers' in result['blocked'][0]['reason']


def test_automatic_save_does_not_leave_empty_review_draft_stale(intake_book):
    lib, _, hit, _ = intake_book; target = hit['section_id']; context = lib.review_context(target)
    p = proposal(context, 'bibliography.title', 'Introduction', 'Introduction')
    result = {'suggestions': [p], 'unresolved': [{'field': 'bibliography.authors', 'reason': 'Please inspect the role.'}]}
    lib.store_review_suggestions(target, result, revision=context['revision'])
    apply(lib, target, [p])
    draft = lib.review_draft(target)
    assert not draft['stale'] and draft['suggestions'] == []
    assert draft['unresolved'] == result['unresolved']
    assert not draft['decisions'] and not draft['changes']


def test_replayed_result_does_not_stale_unrelated_remaining_suggestion(intake_book):
    lib, _, hit, _ = intake_book; target = hit['section_id']; context = lib.review_context(target)
    valid = proposal(context, 'bibliography.title', 'Introduction', 'Introduction')
    manual = proposal(context, 'profile.subjects', ['neuroscience'], 'Introduction', relationship='subject_classification')
    result = {'suggestions': [valid, manual], 'unresolved': []}
    lib.store_review_suggestions(target, result, revision=context['revision'])
    apply(lib, target, [valid, manual])
    # Queue recovery stores the durable original result again after the commit.
    lib.store_review_suggestions(target, result, revision=context['revision'])
    apply_automatic(lib, target, result, intake_id='intake_fixture', request_id='once', revision=context['revision'])
    draft = lib.review_draft(target)
    assert not draft['stale'] and len(draft['suggestions']) == 1
    assert draft['suggestions'][0]['field'] == 'profile.subjects' and not draft['suggestions'][0]['stale']


def test_automatic_save_never_rebases_unrelated_manual_work(intake_book):
    lib, _, hit, _ = intake_book; target = hit['section_id']; context = lib.review_context(target)
    manual = lib.save_review_draft(target, {'profile.subjects': {'value': ['my topic'], 'evidence': 'My work.', 'verified': False}},
                                   revision=context['revision'], expected_version=0)
    p = proposal(context, 'bibliography.title', 'Introduction', 'Introduction')
    result = apply(lib, target, [p])
    draft = lib.review_draft(target)
    assert result['needs_review']
    assert draft['changes'] == manual['changes'] and draft['revision'] == manual['revision']


def test_scripture_reference_is_not_uniform_scripture_evidence(intake_book):
    lib, _, hit, _ = intake_book; target = hit['section_id']; context = lib.review_context(target)
    p = proposal(context, 'text_type', 'scripture', 'This book explains the purpose and arrangement of the collection for readers interested in worship.', relationship='subject_classification')
    result = apply(lib, target, [p])
    assert not result['saved'] and 'entire target' in result['blocked'][0]['reason']


def test_credit_suffix_is_preserved(tmp_path):
    source = docx(tmp_path / 'Collection' / 'book.docx', [
        ('Heading1', 'Introduction'), 'Written by Jane van Doe, Jr.',
        'This introduction explains the purpose and arrangement of the material for its readers.',
    ])
    lib = seed(tmp_path, [{'title': 'Collection', 'author': 'Unknown', 'paths': [source]}])
    target = lib.search('arrangement', engine='exact')['direct'][0]['section_id']; context = lib.review_context(target)
    p = proposal(context, 'bibliography.authors', [{'given': 'Jane', 'family': 'van Doe', 'suffix': 'Jr.'}],
                 'Written by Jane van Doe, Jr.', relationship='direct_credit')
    assert apply(lib, target, [p])['saved']
    assert field(lib, target, 'bibliography.authors')['value'] == [{'literal': 'Jane van Doe, Jr.'}]


def test_explicit_adjacent_role_label_and_name_are_supported(tmp_path):
    source = docx(tmp_path / 'Collection' / 'book.docx', [
        ('Heading1', 'Publication'), 'A Collection', 'Edited by', 'Jane Doe',
        ('Heading1', 'Introduction'), 'This introduction explains the purpose and arrangement of the material for its readers.',
    ])
    lib = seed(tmp_path, [{'title': 'A Collection', 'author': 'Unknown', 'paths': [source]}])
    target = lib.search('arrangement', engine='exact')['direct'][0]['work_id']; context = lib.review_context(target)
    p = proposal(context, 'bibliography.editors', [{'literal': 'Jane Doe'}], 'Edited by', relationship='direct_credit')
    name = next(e for e in context['evidence'] if e['text'] == 'Jane Doe')
    p['evidence'].append({'source_id': name['id'], 'quote': name['text'], 'read_url': name['read_url']})
    assert apply(lib, target, [p])['saved']
    assert field(lib, target, 'bibliography.editors')['value'] == [{'literal': 'Jane Doe'}]


@pytest.mark.parametrize('year,report,expected', [
    ('2015', 'ISBN 9781611645286. Copyright 2015. Published in 2026.', False),
    ('2025', 'ISBN 9781611645286. Published in 2025.', False),
    ('2026', 'ISBN 9781611645286. Published in 2026.', True),
])
def test_external_publication_year_requires_assertion_and_no_copy_conflict(intake_book, year, report, expected):
    from book_library.storage import atomic_json
    lib, _, hit, _ = intake_book; target = hit['work_id']
    catalog = lib._catalog(); catalog['works'][target].setdefault('metadata', {})['isbn'] = '9781611645286'
    atomic_json(lib.state / 'catalog.json', catalog)
    p = {'field': 'bibliography.year', 'value': year, 'strength': 'well_supported',
         'rationale': 'The matching edition record supplies the year.', 'scope_supported': True, 'edition_match': True,
         'evidence': [{'source_id': 'external_record', 'url': 'https://loc.gov/item/book/', 'summary': report}],
         'reported_facts': [{'source_id': 'external_record', 'kind': 'isbn', 'value': '9781611645286'},
                            {'source_id': 'external_record', 'kind': 'year', 'value': year, 'record_isbn': '9781611645286'}]}
    result = apply(lib, target, [p], external_report={'sources': [{'id': 'external_record', 'url': 'https://loc.gov/item/book/', 'cited_report_text': report}]})
    assert result['saved'] is expected
