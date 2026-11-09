"""Scripture, scholarly notes, and mixed source spans keep separate identities."""
from __future__ import annotations

import json
import pytest
from fastapi.testclient import TestClient

from book_library.citations import cite_passage, validate_bibliography
from book_library.web import create_app
from test_citations import bib, page
from test_citation_web import ORIGIN, form_values, post, tree
from test_passage_curation import mixed_source, passage_credit
from test_service import docx, seed


def scripture_metadata(**patch):
    return {'type':'scripture', 'scripture_scope':'text_only',
            'bible_translation':'New Revised Standard Version Updated Edition',
            'bible_translation_short':'NRSVue',
            'locator':{'type':'verse','value':'Matthew 5:1–12','verified':True,
                       'evidence':'Printed book and chapter/verse markers inspected in this fixture.'}, **patch}


def test_scripture_citation_does_not_make_editor_or_commentator_its_author(tmp_path):
    lib, commentary, scripture, _ = mixed_source(tmp_path)
    passage_credit(lib, commentary)
    bib(lib, scripture['id'], scripture_metadata(), origin='codex')
    result = cite_passage(lib, scripture['id'])
    assert result['ready'] and not result['missing_fields']
    assert result['full_note'] == 'Matthew 5:1–12 (New Revised Standard Version Updated Edition).'
    assert result['short_note'] == 'Matthew 5:1–12 (NRSVue).'
    assert result['bibliography'] == '' and result['bibliography_required'] is False
    assert result['metadata']['authors'] == result['metadata']['editors'] == []
    assert 'Gale' not in result['full_note'] and 'Editor' not in result['full_note']
    assert cite_passage(lib, commentary['id'])['full_note'].startswith('Aaron M. Gale,')
    lib.sync(semantic=False)
    hit = lib.search('violet biblical', engine='exact')['direct'][0]
    assert hit['attribution'] == 'Scripture — NRSVue'
    assert not any('contributor requires verification' in warning.lower() for warning in hit['limitations'])
    reading = lib.read(scripture['id'], context=1)
    assert next(block for block in reading['blocks'] if 'Copper commentary.' in block['text'])['attribution'] == 'Aaron M. Gale'


@pytest.mark.parametrize('patch,field', [
    ({'bible_translation':None}, 'section.bible_translation'),
    ({'scripture_scope':None}, 'section.scripture_scope'),
    ({'scripture_scope':'mixed'}, 'section.scripture_scope'),
    ({'locator':page('42')}, 'locator'),
    ({'locator':{'type':'verse','value':'5:1–12','verified':True,'evidence':'No book recorded'}}, 'locator'),
])
def test_scripture_missing_translation_scope_or_canonical_reference_is_not_ready(tmp_path, patch, field):
    lib, _, scripture, _ = mixed_source(tmp_path)
    bib(lib, scripture['id'], scripture_metadata(**patch), origin='codex')
    result = cite_passage(lib, scripture['id'])
    assert not result['ready']
    assert field in result['missing_fields'] + result['review_fields']
    lib.sync(semantic=False)
    if field != 'locator':
        assert lib.search('violet biblical', engine='exact')['direct'][0]['limitations']


@pytest.mark.parametrize('status', ['provisional','disputed'])
def test_scripture_status_cannot_silently_confirm_translation_or_scope(tmp_path, status):
    lib, _, scripture, _ = mixed_source(tmp_path)
    bib(lib, scripture['id'], scripture_metadata(), origin='codex', status=status)
    result = cite_passage(lib, scripture['id'])
    assert not result['ready']
    assert set(result['review_fields']) >= {'section.type','section.scripture_scope','section.bible_translation','locator'}
    lib.sync(semantic=False)
    hit = lib.search('violet biblical', engine='exact')['direct'][0]
    assert hit['attribution'] == 'Scripture classification requires verification'
    assert any('classification' in warning.lower() for warning in hit['limitations'])


def segmented_source(tmp_path, status='confirmed'):
    source = docx(tmp_path/'books'/'Study Bible'/'Mixed.docx', [
        ('Heading1','Matthew'), 'Blessed copper peacemakers in the biblical text.',
        'Violet scholarly commentary explains the Beatitudes.'])
    lib = seed(tmp_path/'books', [{'title':'A Study Bible','author':'Volume Editor','paths':[source],
                                 'metadata':{'editors':['Volume Editor']}}])
    hit = lib.search('copper peacemakers', engine='exact')['direct'][0]
    bib(lib, hit['work_id'], {'title':'A Study Bible','authors':[],
        'editors':[{'given':'Volume','family':'Editor'}], 'publisher':'Example Press','year':2026})
    blocks = lib.read(hit['id'],context=0)['blocks']
    segments = [
        {'first_block_id':blocks[0]['id'],'last_block_id':blocks[1]['id'],
         'text_type':'scripture','attribution':'Scripture — NRSVue','bibliography':scripture_metadata()},
        {'first_block_id':blocks[2]['id'],'last_block_id':blocks[2]['id'],
         'text_type':'commentary','attribution':'Aaron M. Gale','bibliography':{
             'type':'chapter','title':'Matthew','authors':[{'given':'Aaron M.','family':'Gale'}],
             'locator':{'type':'section','value':'Matthew 5 annotations','verified':True,'evidence':'Inspected annotation label.'}}},
    ]
    lib.annotate(hit['id'], {'field':'segments','value':segments,'origin':'codex','status':status,
                           'evidence':'Inspected boundaries, translation credit, and annotation byline in fixture.'})
    return lib, hit, segments


def test_mixed_passage_offers_separate_citations_without_borrowing_any_author(tmp_path):
    lib, hit, segments = segmented_source(tmp_path)
    # A broader wrong credit must not leak into the explicit source components.
    bib(lib, hit['section_id'], {'type':'chapter','title':'Wrong inherited title',
                               'authors':[{'literal':'Wrong Neighbor'}], 'locator':page('99')})
    parent = cite_passage(lib, hit['id'])
    assert not parent['ready'] and parent['review_fields'] == ['choose_component']
    assert parent['full_note'] == parent['short_note'] == parent['bibliography'] == ''
    assert len(parent['component_citations']) == 2
    bible, scholar = parent['component_citations']
    assert bible['ready'] and scholar['ready']
    assert bible['full_note'].startswith('Matthew 5:1–12 (New Revised')
    assert scholar['full_note'].startswith('Aaron M. Gale, “Matthew,”')
    assert 'Wrong' not in bible['full_note'] + scholar['full_note']
    assert bible['citation_id'] != scholar['citation_id']
    assert bible['source_identity']['source_block_ids'] == [segments[0]['first_block_id'],segments[0]['last_block_id']]
    selected = cite_passage(lib, hit['id'],segment_id=segments[1]['first_block_id'])
    assert selected['full_note'] == scholar['full_note']
    assert selected['metadata_scope'] == 'segment'
    with pytest.raises(ValueError,match='Unknown source component'):
        cite_passage(lib, hit['id'],segment_id='block_missing')


def test_unverified_component_event_keeps_each_citation_in_review(tmp_path):
    lib, hit, _ = segmented_source(tmp_path,status='provisional')
    results = cite_passage(lib,hit['id'])['component_citations']
    assert all(result['needs_review'] for result in results)
    assert 'section.bible_translation' in results[0]['review_fields']
    assert 'section.authors' in results[1]['review_fields']


def test_scripture_component_api_keeps_selection_and_bibliography_scope(tmp_path):
    lib, hit, segments = segmented_source(tmp_path)
    with TestClient(create_app(lib, enable_intake_worker=False),base_url=ORIGIN) as client:
        parent = tree(client.get('/api/ui/cite/'+hit['id']))
        components = parent['citation']['component_citations']
        assert len(components) == 2
        assert all(component['links']['local_citation'] for component in components)
        assert parent['citation']['review_fields'] == ['choose_component']
        assert parent['citation']['full_note'] == parent['citation']['bibliography'] == ''
        selection = segments[0]['first_block_id']
        document = tree(client.get('/api/ui/cite/'+hit['id'],params={'segment':selection}))
        assert 'Matthew 5:1–12' in document['citation']['full_note']
        assert document['citation']['bibliography_required'] is False
        assert document['citation']['bibliography'] == ''
        assert document['citation']['metadata_scope'] == 'segment'
        assert document['segment_id'] == selection
        action='/cite/'+hit['id']+'/export'
        values = form_values(document,action)
        assert values['segment'] == selection
        values['format']='json'
        result = post(client,action,values).json()
        assert result['segment_id'] == selection and result['ready']
        assert result['full_note'] == document['citation']['full_note']
        assert result['bibliography_required'] is False


def test_scripture_editor_preserves_scope_and_returns_translation_as_data(tmp_path):
    lib, _, scripture, _ = mixed_source(tmp_path)
    hostile = '<script>alert("source")</script>'
    bib(lib,scripture['id'],scripture_metadata(bible_translation=hostile),origin='codex')
    with TestClient(create_app(lib, enable_intake_worker=False),base_url=ORIGIN) as client:
        action='/bibliography/'+scripture['id']
        response = client.get('/api/ui'+action,params={'passage':scripture['id']})
        editor = tree(response)
        values = form_values(editor,action)
        assert values['type'] == 'scripture' and values['scripture_scope'] == 'text_only'
        assert values['bible_translation'] == hostile
        assert editor['target']['scope'] == 'passage'
        assert response.headers['content-type'].startswith('application/json')
        assert "script-src 'self'" in response.headers['content-security-policy']
        # Raw source strings remain JSON data; React tests enforce safe text rendering.
        unsafe_citation = tree(client.get('/api/ui/cite/'+scripture['id']))['citation']
        assert hostile in unsafe_citation['full_note']
        assert '<script>' not in unsafe_citation['html']['full_note']
        assert '&lt;script&gt;' in unsafe_citation['html']['full_note']
        values.update(bible_translation='New Revised Standard Version Updated Edition',evidence='Inspected translation statement.')
        saved = post(client,action,values)
        assert saved.status_code == 200
        assert saved.json()['redirect'] == '/cite/'+scripture['id']+'?saved=true'
        citation = tree(client.get('/api/ui/cite/'+scripture['id']))['citation']
        assert citation['metadata_scope'] == 'passage'
        assert citation['metadata']['bible_translation'] == 'New Revised Standard Version Updated Edition'
        assert hostile not in citation['full_note']
    assert cite_passage(lib,scripture['id'])['ready']


def test_scripture_schema_rejects_unknown_scope(tmp_path):
    with pytest.raises(ValueError,match='scope'):
        validate_bibliography(scripture_metadata(scripture_scope='probably_scripture'))


def test_selected_component_only_reports_its_own_credit_limitations(tmp_path):
    lib, hit, segments = segmented_source(tmp_path)
    segments[1]['attribution'] = 'Contributor unverified'
    segments[1]['text_type'] = 'unknown'
    segments[1]['bibliography']['authors'] = None
    lib.annotate(hit['id'], {'field':'segments','value':segments,'origin':'codex','status':'confirmed',
                           'evidence':'Bible text is verified, but the scholarly credit is unresolved.'})
    lib.sync(semantic=False)
    bible = cite_passage(lib,hit['id'],segment_id=segments[0]['first_block_id'])
    assert bible['ready']
    assert not any('described portion' in warning or 'separately credited portions' in warning for warning in bible['warnings'])
    unknown = cite_passage(lib,hit['id'],segment_id=segments[1]['first_block_id'])
    assert not unknown['ready']
    assert 'component.attribution' in unknown['review_fields']


def test_section_scripture_credit_is_distinct_from_the_volume_editor(tmp_path):
    source = docx(tmp_path/'books'/'Bible'/'text.docx', [('Heading1','Matthew'),
                                                       'Copper peacemakers are blessed.'])
    lib = seed(tmp_path/'books',[{'title':'An Annotated Bible','author':'Volume Editor','paths':[source],
                                  'metadata':{'editors':['Volume Editor']}}])
    hit=lib.search('copper peacemakers',engine='exact')['direct'][0]
    bib(lib,hit['section_id'],scripture_metadata(),origin='codex')
    result=cite_passage(lib,hit['id'])
    assert result['ready'] and result['attribution']=='Scripture — NRSVue'
    assert not any('contributor requires verification' in warning.lower() for warning in result['warnings'])
