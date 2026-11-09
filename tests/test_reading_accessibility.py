"""Reader API preserves order and metadata for accessible React grouping.

DOM grouping, focus targets, links, and escaping are exercised by
frontend/src/components/SourceBlocks.test.tsx and ReadingPages.test.tsx.
"""
from copy import deepcopy
from fastapi.testclient import TestClient
from book_library.web import create_app
from test_web import FakeLibrary, ORIGIN


def reading_page(blocks):
    library = FakeLibrary()
    original = library.read
    def read(passage_id, context=3):
        result = original(passage_id, context)
        result['blocks'] = deepcopy(blocks)
        return result
    library.read = read
    with TestClient(create_app(library, enable_intake_worker=False), base_url=ORIGIN) as client:
        response = client.get('/api/ui/read/passage-1')
    assert response.status_code == 200
    return response.json()['data']['reading']


def block(text, location='Page 10', author='Poem by C. Poet', selected=True, **extra):
    return {'id': '', 'kind': 'paragraph', 'text': text, 'location': location,
            'attribution': author, 'selected': selected, **extra}


def test_consecutive_poetry_lines_preserve_breaks_and_shared_metadata():
    lines = ['The first line\ncontinues here.', 'The second line.', 'The third line.']
    reading = reading_page([block(line) for line in lines])
    assert [item['text'] for item in reading['blocks']] == lines
    assert all(item['location'] == 'Page 10' for item in reading['blocks'])
    assert all(item['attribution'] == 'Poem by C. Poet' for item in reading['blocks'])
    assert all(item['selected'] for item in reading['blocks'])
    assert reading['next'] == 'passage-2'


def test_context_and_credit_changes_preserve_exact_matched_boundaries():
    blocks = [
        block('Earlier context.', author='Earlier contributor', selected=False),
        block('Earlier continuation.', author='Earlier contributor', selected=False),
        block('Matched first line.', location='Page 11', author='Chapter by B. Writer'),
        block('Matched second line.', location='Page 11', author='Chapter by B. Writer'),
        block('Next source.', location='Page 12', author='Following contributor', selected=False),
    ]
    reading = reading_page(blocks)
    assert reading['blocks'] == blocks
    assert [item['text'] for item in reading['blocks'] if item['selected']] == [
        'Matched first line.', 'Matched second line.']


def test_illustration_reference_keeps_caption_and_source_identity():
    blocks = [block('', kind='image', file_id='file-1', image_refs=['EPUB/images/figure.jpg']), block('Figure 1. Source caption.')]
    reading = reading_page(blocks)
    assert reading['blocks'] == blocks
    assert reading['blocks'][0]['file_id'] == 'file-1'
    assert reading['blocks'][0]['image_refs'] == ['EPUB/images/figure.jpg']
    assert reading['blocks'][1]['text'] == 'Figure 1. Source caption.'
