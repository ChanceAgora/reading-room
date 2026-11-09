"""A commentary credit must not leak into adjacent biblical text in one section."""
from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from book_library.web import create_app
from test_citation_web import ORIGIN, form_values, post, tree
from test_citations import bib, page
from test_service import docx, seed


COMMENTARY = 'Copper commentary. ' + ('This annotation explains the wording and historical setting of the passage. ' * 27)
BIBLICAL_TEXT = 'Violet biblical text. Blessed are the peacemakers, for they will be called children of God.'
AUTHOR = {'given': 'Aaron M.', 'family': 'Gale'}


def mixed_source(tmp_path):
    source = docx(tmp_path / 'books' / 'Study Bible' / 'Mixed.docx', [
        ('Heading1', 'Matthew and annotations'), COMMENTARY, BIBLICAL_TEXT])
    lib = seed(tmp_path / 'books', [{
        'title': 'An Annotated Bible', 'author': 'Volume Editor', 'paths': [source],
        'metadata': {'editors': ['Volume Editor']}}])
    commentary = lib.search('copper commentary', engine='exact')['direct'][0]
    scripture = lib.search('violet biblical', engine='exact')['direct'][0]
    assert commentary['id'] != scripture['id']
    assert commentary['section_id'] == scripture['section_id']
    bib(lib, commentary['work_id'], {
        'title': 'An Annotated Bible', 'authors': [],
        'editors': [{'given': 'Volume', 'family': 'Editor'}],
        'publisher': 'Example Press', 'year': '2026', 'edition': '3rd ed.',
        'format': 'Bookshare Word edition'})
    return lib, commentary, scripture, source


def passage_credit(lib, hit, **patch):
    return bib(lib, hit['id'], {
        'type': 'entry', 'title': 'The Beatitudes and Extensions', 'authors': [AUTHOR],
        'locator': {'type': 'section', 'value': 'Matthew: The Beatitudes and Extensions',
                    'verified': True, 'evidence': 'The exact sidebar heading and byline in this fixture.'},
        **patch}, origin='codex')


def test_passage_citation_applies_immediately_without_crediting_neighbor(tmp_path):
    lib, commentary, scripture, _ = mixed_source(tmp_path)
    event = passage_credit(lib, commentary)
    result = lib.cite(commentary['id'])
    assert result['ready']
    assert result['full_note'].startswith('Aaron M. Gale, “The Beatitudes and Extensions,”')
    assert 'ed. Volume Editor' in result['full_note']
    assert result['bibliography'].startswith('Gale, Aaron M.')
    assert result['metadata_scope'] == 'passage'
    assert result['contribution_target_id'] == commentary['id']
    assert result['provenance']['section.authors']['target_id'] == commentary['id']
    assert result['provenance']['section.authors']['annotation_id'] == event['id']
    assert not any('Section contributor requires verification' in warning for warning in result['warnings'])
    other = lib.cite(scripture['id'], page())
    assert 'Aaron' not in other['full_note']
    assert 'section.authorship' in other['review_fields']
    assert lib.bibliography_record(commentary['section_id'])['record'] == {}


def test_sync_search_and_context_keep_passage_credit_scoped(tmp_path):
    lib, commentary, scripture, _ = mixed_source(tmp_path)
    passage_credit(lib, commentary)
    lib.sync(semantic=False)
    found = lib.search('copper commentary', engine='exact')['direct'][0]
    assert found['attribution'] == 'Aaron M. Gale'
    assert not any('contributor requires verification' in limitation.lower() for limitation in found['limitations'])
    other = lib.search('violet biblical', engine='exact')['direct'][0]
    assert 'unverified' in other['attribution'].lower()
    assert lib.search('copper commentary', filters={'author': 'Gale'}, engine='exact')['direct']
    assert not lib.search('violet biblical', filters={'author': 'Gale'}, engine='exact')['direct']
    for selected, context in ((commentary, scripture), (scripture, commentary)):
        reading = lib.read(selected['id'], context=1, max_chars=8000)
        copper = next(block for block in reading['blocks'] if 'Copper commentary.' in block['text'])
        violet = next(block for block in reading['blocks'] if 'Violet biblical text.' in block['text'])
        assert copper['attribution'] == 'Aaron M. Gale'
        assert 'unverified' in violet['attribution'].lower()
        assert copper['selected'] == (selected['id'] == commentary['id'])
        assert violet['selected'] == (selected['id'] == scripture['id'])
    assert 'unverified' in lib.read(commentary['id'])['section']['attribution'].lower()


def test_passage_overrides_layer_over_section_with_field_provenance(tmp_path):
    lib, commentary, scripture, _ = mixed_source(tmp_path)
    bib(lib, commentary['section_id'], {
        'type': 'entry', 'title': 'A section contribution',
        'authors': [{'given': 'Section', 'family': 'Writer'}], 'locator': page('11')})
    bib(lib, commentary['id'], {'authors': [AUTHOR]}, origin='codex')
    result = lib.cite(commentary['id'])
    assert result['full_note'].startswith('Aaron M. Gale, “A section contribution,”')
    assert result['provenance']['section.authors']['target_id'] == commentary['id']
    assert result['provenance']['section.title']['target_id'] == commentary['section_id']
    assert lib.cite(scripture['id'])['full_note'].startswith('Section Writer, “A section contribution,”')


@pytest.mark.parametrize('status', ['provisional', 'disputed'])
def test_unverified_passage_author_retains_warning_before_and_after_sync(tmp_path, status):
    lib, commentary, scripture, _ = mixed_source(tmp_path)
    bib(lib, commentary['section_id'], {
        'type': 'entry', 'title': 'A section contribution',
        'authors': [{'given': 'Section', 'family': 'Writer'}], 'locator': page('11')})
    bib(lib, commentary['id'], {'authors': [AUTHOR]}, status=status, origin='codex')
    for synchronize in (False, True):
        if synchronize:
            lib.sync(semantic=False)
        result = lib.cite(commentary['id'])
        assert not result['ready']
        assert 'section.authors' in result['review_fields']
        assert result['provenance']['section.authors']['status'] == status
        assert any('Passage contributor requires verification' in warning for warning in result['warnings'])
        assert lib.cite(scripture['id'])['full_note'].startswith('Section Writer,')
    result = lib.search('copper commentary', engine='exact')['direct'][0]
    assert any('Passage contributor requires verification' in warning for warning in result['limitations'])


def test_null_passage_author_is_unknown_and_does_not_inherit_section_author(tmp_path):
    lib, commentary, scripture, _ = mixed_source(tmp_path)
    bib(lib, commentary['section_id'], {
        'type': 'entry', 'title': 'A section contribution',
        'authors': [{'given': 'Section', 'family': 'Writer'}], 'locator': page('11')})
    bib(lib, commentary['id'], {'authors': None}, origin='codex')
    before = lib.cite(commentary['id'])
    assert not before['ready']
    assert before['metadata']['authors'] == []
    assert 'section.authors' in before['missing_fields']
    assert 'Section Writer' not in before['full_note']
    assert 'unverified' in before['attribution'].lower()
    lib.sync(semantic=False)
    hit = lib.search('copper commentary', engine='exact')['direct'][0]
    assert hit['attribution'] == 'Contributor unverified'
    assert any('Passage contributor requires verification' in warning for warning in hit['limitations'])
    assert 'Section Writer' not in lib.cite(commentary['id'])['full_note']
    assert lib.cite(scripture['id'])['full_note'].startswith('Section Writer,')


def test_user_passage_correction_and_explicit_attribution_survive_rename_rebuild(tmp_path):
    lib, commentary, _, source = mixed_source(tmp_path)
    passage_credit(lib, commentary)
    bib(lib, commentary['id'], {'authors': [{'given': 'Corrected', 'family': 'Contributor'}]}, origin='user')
    bib(lib, commentary['id'], {'authors': [{'given': 'Wrong', 'family': 'Guess'}]}, origin='codex')
    lib.annotate(commentary['id'], {'field': 'attribution', 'value': 'Commentary by Corrected Contributor',
                                  'origin': 'user', 'status': 'confirmed',
                                  'evidence': 'Explicit scoped credit for this commentary only.'})
    lib.annotate(commentary['id'], {'field': 'notes', 'value': 'The next passage is scripture, not this commentary.',
                                  'origin': 'codex', 'status': 'confirmed',
                                  'evidence': 'Boundary inspected in fixture.'})
    lib.sync(semantic=False)
    original_id = commentary['id']
    renamed = source.with_name('Semantically Named.docx')
    source.rename(renamed)
    lib.sync(semantic=False)
    lib.sync(rebuild=True, semantic=False)
    hit = lib.search('copper commentary', engine='exact')['direct'][0]
    assert hit['id'] == original_id
    assert hit['attribution'] == 'Commentary by Corrected Contributor'
    assert hit['source_paths'] == [str(renamed)]
    citation = lib.cite(original_id)
    assert citation['full_note'].startswith('Corrected Contributor,')
    assert citation['attribution'] == 'Commentary by Corrected Contributor'
    assert citation['provenance']['section.authors']['origin'] == 'user'
    assert citation['ready']
    assert lib.bibliography_record(original_id)['record']['authors'] == [{'given': 'Corrected', 'family': 'Contributor'}]
    assert lib.status()['orphaned_curation_count'] == 0


def test_changed_source_retains_but_does_not_transfer_passage_credit(tmp_path):
    lib, commentary, _, source = mixed_source(tmp_path)
    event = passage_credit(lib, commentary)
    lib.sync(semantic=False)
    docx(source, [('Heading1', 'Matthew and annotations'),
                 COMMENTARY.replace('Copper commentary.', 'Amber replacement.'), BIBLICAL_TEXT])
    lib.sync(semantic=False)
    replacement = lib.search('amber replacement', engine='exact')['direct'][0]
    assert replacement['id'] != commentary['id']
    assert 'unverified' in replacement['attribution'].lower()
    assert 'Aaron M. Gale' not in lib.cite(replacement['id'])['full_note']
    assert any(item['id'] == event['id'] for item in lib._curation())
    assert commentary['id'] in lib.status()['orphaned_curation']
    assert lib.status()['orphaned_passage_curation_count'] == 1
    with pytest.raises(ValueError):
        lib.bibliography_record(commentary['id'])


@pytest.mark.parametrize(('field', 'value'), [
    ('profile', {'subjects': ['theology']}), ('title', 'Changed'), ('author', 'Another person'),
    ('contributors', [{'name': 'Another person', 'role': 'author'}]), ('coverage', ['Matthew 5'])])
def test_passage_scope_rejects_non_passage_fields(tmp_path, field, value):
    lib, commentary, _, _ = mixed_source(tmp_path)
    count = len(lib._curation())
    with pytest.raises(ValueError, match='[Pp]assage'):
        lib.annotate(commentary['id'], {'field': field, 'value': value, 'origin': 'codex',
                                      'status': 'confirmed', 'evidence': 'Would affect the wrong scope.'})
    assert len(lib._curation()) == count


def test_unknown_passage_cannot_receive_curation(tmp_path):
    lib, _, _, _ = mixed_source(tmp_path)
    with pytest.raises(ValueError, match='Unknown'):
        bib(lib, 'passage_does_not_exist', {'authors': [AUTHOR]})


def test_passage_editor_declares_scope_and_does_not_edit_section(tmp_path):
    lib, commentary, scripture, _ = mixed_source(tmp_path)
    passage_credit(lib, commentary)
    target = lib.bibliography_record(commentary['id'])
    assert target['scope'] == 'passage' and target['is_passage'] and target['is_section']
    assert target['work_id'] == commentary['work_id']
    action = f"/bibliography/{commentary['id']}"
    with TestClient(create_app(lib, enable_intake_worker=False), base_url=ORIGIN) as client:
        citation_page = tree(client.get(f"/api/ui/cite/{commentary['id']}"))
        # React renders the passage-only warning and links from these identities.
        assert citation_page['citation']['metadata_scope'] == 'passage'
        assert citation_page['citation']['contribution_target_id'] == commentary['id']
        assert citation_page['passage']['id'] == commentary['id']
        document = tree(client.get('/api/ui' + action + '?passage=' + commentary['id']))
        assert document['target']['scope'] == 'passage'
        assert document['target']['is_passage'] is True
        assert document['target']['section_id'] == commentary['section_id']
        assert document['passage_id'] == commentary['id']
        values = form_values(document, action)
        values.update(title='The Correct Sidebar Title', evidence='Verified this individual commentary heading.')
        saved = post(client, action, values)
        assert saved.status_code == 200
        assert saved.json()['redirect'] == f"/cite/{commentary['id']}?saved=true"
    result = lib.cite(commentary['id'])
    assert '“The Correct Sidebar Title,”' in result['full_note']
    assert result['provenance']['section.authors']['origin'] == 'codex'
    assert result['provenance']['section.title']['origin'] == 'user'
    assert lib.bibliography_record(commentary['section_id'])['record'] == {}
    assert 'The Correct Sidebar Title' not in lib.cite(scripture['id'])['full_note']
