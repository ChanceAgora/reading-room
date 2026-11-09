"""Cheap book-level citation metadata coverage; never certify unread passages."""


def metadata_coverage(works, edits):
    fields = ('title', 'creator', 'publisher', 'year')
    counts = dict.fromkeys(fields, 0)
    reviewed = 0
    complete = 0
    samples = []
    for work_id, work in works.items():
        event = edits.get((work_id, 'bibliography'), {})
        values = event.get('value', {})
        reviewed += bool(values)

        def verified(field):
            source = event.get('field_events', {}).get(field, event)
            return field in values and source.get('status') == 'confirmed' and bool(source.get('evidence'))

        known = {field: bool(values.get(field)) and verified(field) for field in ('title', 'publisher', 'year')}
        known['creator'] = any(values.get(role) and verified(role) for role in ('authors', 'editors', 'translators')) or (values.get('authors') == [] and verified('authors'))
        for field in fields:
            counts[field] += bool(known[field])
        missing = [field for field in fields if not known[field]]
        complete += not missing
        if missing and len(samples) < 12:
            samples.append({'work_id': work_id, 'title': work.get('title', work_id), 'needs_review': missing})
    return {
        'books_with_bibliographic_curation': reviewed,
        'books_with_title_creator_publisher_year_verified': complete,
        'books_needing_core_metadata_review': len(works) - complete,
        'verified_field_counts': counts,
        'review_sample': samples,
        'scope': 'Book-level metadata only. Individual contributions, consulted edition details, and passage locators still need their own checks; use cite for a passage-specific assessment.',
    }
