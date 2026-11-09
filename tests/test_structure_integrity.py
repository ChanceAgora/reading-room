"""Projection must not promote a different metadata field's verification."""
from test_service import docx, seed


def test_contents_author_verification_uses_authors_field_not_title_status(tmp_path):
    root = tmp_path / 'books'
    path = docx(root / 'Book' / 'book.docx', [('Heading1', 'Essay'), 'Source body text.'])
    lib = seed(root, [{'title': 'Collected essays', 'author': 'Volume Editor', 'paths': [path]}])
    hit = lib.search('Source body', engine='exact')['direct'][0]
    lib.annotate(hit['section_id'], {'field': 'bibliography', 'value': {'type': 'chapter', 'title': 'Essay'},
                                    'origin': 'codex', 'status': 'confirmed', 'evidence': 'Verified source title.'})
    lib.annotate(hit['section_id'], {'field': 'bibliography', 'value': {'authors': [{'literal': 'Candidate Writer'}]},
                                    'origin': 'codex', 'status': 'provisional', 'evidence': 'Unverified contributor candidate.'})
    lib.sync(semantic=False)
    node = next(n for n in lib.contents(hit['work_id'])['nodes'] if n['title'] == 'Essay')
    assert not node['attribution_verified']
    assert not lib.read_unit(node['unit_id'])['unit']['attribution_verified']
    # Confirming this exact field subsequently makes the display credit usable.
    lib.annotate(hit['section_id'], {'field': 'bibliography', 'value': {'authors': [{'literal': 'Candidate Writer'}]},
                                    'origin': 'codex', 'status': 'confirmed', 'evidence': 'Verified closing byline and roster.'})
    lib.sync(semantic=False)
    node = next(n for n in lib.contents(hit['work_id'])['nodes'] if n['title'] == 'Essay')
    assert node['attribution_verified']
    assert lib.read_unit(node['unit_id'])['unit']['attribution_verified']
