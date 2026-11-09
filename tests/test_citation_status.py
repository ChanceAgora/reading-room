from book_library.citation_status import metadata_coverage


def event(values, status='confirmed'):
    return {'value': values, 'status': status, 'evidence': 'Title-page fixture'}


def test_coverage_counts_evidence_backed_fields_not_catalog_guesses():
    works = {'a': {'title': 'Verified'}, 'b': {'title': 'Candidate'}}
    edits = {('a', 'bibliography'): event({'title': 'Verified', 'authors': [{'given': 'Ann', 'family': 'Author'}], 'publisher': 'Press', 'year': 2024}),
             ('b', 'bibliography'): event({'title': 'Candidate', 'authors': [], 'publisher': 'Press', 'year': 2020}, 'provisional')}
    result = metadata_coverage(works, edits)
    assert result['books_with_title_creator_publisher_year_verified'] == 1
    assert result['verified_field_counts'] == dict.fromkeys(('title', 'creator', 'publisher', 'year'), 1)
    assert result['review_sample'][0]['work_id'] == 'b'


def test_cleared_author_is_unknown_but_explicit_empty_or_verified_editor_counts():
    works = {key: {'title': key} for key in ('unknown', 'anonymous', 'edited')}
    edits = {(key, 'bibliography'): event({'title': key, 'publisher': 'Press', 'year': 2024, **value}) for key, value in
             [('unknown', {'authors': None}), ('anonymous', {'authors': []}), ('edited', {'editors': [{'literal': 'Editorial Council'}]})]}
    result = metadata_coverage(works, edits)
    assert result['books_with_title_creator_publisher_year_verified'] == 2
    assert result['review_sample'][0]['needs_review'] == ['creator']


def test_each_field_uses_own_provenance_and_review_list_is_bounded():
    works = {str(i): {'title': str(i)} for i in range(20)}
    item = event({'title': '0', 'authors': [], 'publisher': 'Press', 'year': 2024})
    item['field_events'] = {'year': {'status': 'provisional', 'evidence': 'Copyright only'}}
    result = metadata_coverage(works, {('0', 'bibliography'): item})
    assert result['books_with_title_creator_publisher_year_verified'] == 0
    assert result['verified_field_counts']['year'] == 0
    assert result['review_sample'][0]['needs_review'] == ['year']
    assert len(result['review_sample']) == 12
