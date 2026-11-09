"""Text type is a source classification, independent of its XML paragraph kind."""
from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from book_library.web import create_app
from book_library.service import Library
from test_citation_web import ORIGIN, post, tree
from test_scripture_citations import segmented_source
from test_passage_curation import mixed_source, passage_credit
from test_service import docx, seed


def classify(lib,target,value,origin='codex',status='confirmed'):
    return lib.annotate(target,{'field':'text_type','value':value,'origin':origin,
                               'status':status,'evidence':'Inspected content and its source boundary.'})


def test_passage_text_type_precedence_filters_and_unknown_holdings(tmp_path):
    lib, commentary, scripture, _=mixed_source(tmp_path)
    classify(lib,commentary['section_id'],'prose')
    classify(lib,commentary['id'],'commentary',origin='user')
    classify(lib,commentary['id'],'poetry',origin='codex')
    passage_credit(lib,commentary)
    lib.sync(semantic=False)
    hit=lib.search('copper commentary',engine='exact')['direct'][0]
    assert hit['text_type']=='commentary'
    assert lib.search('copper commentary',engine='exact',filters={'text_type':'commentary'})['direct']
    assert not lib.search('copper commentary',engine='exact',filters={'text_type':'poetry'})['direct']
    assert lib.search('violet biblical',engine='exact',filters={'text_type':'prose'})['direct']
    assert lib.read(commentary['id'],context=0)['blocks'][1]['text_type']=='commentary'
    with pytest.raises(ValueError,match='text type'):
        lib.search('copper',engine='exact',filters={'text_type':'probably'})
    with pytest.raises(ValueError,match='text type'):
        classify(lib,commentary['id'],'probably')


def test_mixed_passages_match_their_own_type_and_each_component_type(tmp_path):
    lib,hit,_=segmented_source(tmp_path)
    lib.sync(semantic=False)
    for kind in ('mixed','scripture','commentary'):
        found=lib.search('copper',engine='exact',filters={'text_type':kind})['direct']
        assert [h['id'] for h in found]==[hit['id']]
    assert not lib.search('copper',engine='exact',filters={'text_type':'poetry'})['direct']


def test_mixed_semantic_filter_matches_the_parent_type(tmp_path,monkeypatch):
    lib,hit,_=segmented_source(tmp_path)
    lib.sync(semantic=False)
    from book_library.storage import atomic_json
    atomic_json(lib.state/'config.json',{'semantic':{'enabled':True,'engine':'openai','full_build_approved':True}})
    import book_library.semantic_library as semantic
    monkeypatch.setattr(semantic,'search',lambda *a,**k:[{'passage_id':hit['id'],'char_start':0,'char_end':50,'window_id':'window_test'}])
    found=lib.search('unrelated',filters={'text_type':'mixed'})['connections']
    assert [h['id'] for h in found]==[hit['id']]


def test_type_only_correction_reaches_reading_blocks_without_changing_attribution(tmp_path):
    lib,commentary,scripture,_=mixed_source(tmp_path)
    before=lib.read(commentary['id'],context=0)['blocks']
    classify(lib,commentary['id'],'commentary')
    lib.sync(semantic=False)
    after=lib.read(commentary['id'],context=0)['blocks']
    assert [b['attribution'] for b in after]==[b['attribution'] for b in before]
    assert all(b.get('text_type')=='commentary' for b in after)
    assert all(b.get('text_type','unknown')=='unknown' for b in lib.read(scripture['id'],context=0)['blocks'])


@pytest.mark.parametrize('status',['provisional','disputed'])
def test_uncertain_type_is_visible_as_uncertain(tmp_path,status):
    lib,commentary,_,_=mixed_source(tmp_path)
    classify(lib,commentary['id'],'commentary',status=status)
    lib.sync(semantic=False)
    hit=lib.search('copper',engine='exact')['direct'][0]
    assert hit['text_type_status']==status
    assert any('Text type is provisional or disputed' in x for x in hit['limitations'])


def test_heading_only_match_explains_what_actually_matched(tmp_path):
    source=docx(tmp_path/'books'/'Test'/'Book.docx',[
        ('Heading1','Beatitudes'), 'Opening material. '+('long source sentence ' *100),
        'Copper unrelated continuation without the query word.'])
    lib=seed(tmp_path/'books',[{'title':'Test','paths':[source]}])
    hits=lib.search('beatitudes',engine='exact')['direct']
    heading_only=next(h for h in hits if 'Copper' in h['text'])
    assert 'heading or credit' in heading_only['reason']
    assert 'Text contains beatitudes' not in heading_only['reason']


def test_text_type_search_views_and_segment_coordinates_are_preserved(tmp_path):
    lib,hit,segments=segmented_source(tmp_path)
    lib.sync(semantic=False)
    with TestClient(create_app(lib),base_url=ORIGIN) as client:
        document=tree(post(client,'/search',{'q':'copper','text_type':'mixed','engine':'exact'}))
        assert document['filters']['text_type']=='mixed'
        assert document['result']['direct'][0]['text_type']=='mixed'
        values={'q':'copper','text_type':'scripture','engine':'exact'}
        posted=post(client,'/search',values)
        assert posted.status_code==200
        assert tree(posted)['filters']['text_type']=='scripture'
        reading=tree(client.get('/api/ui/read/'+hit['id']))['reading']
        segment_blocks=[block for block in reading['blocks'] if block.get('segment_id')]
        assert len({block['segment_id'] for block in segment_blocks})==2
        assert all(block.get('text_type') and block['passage_id']==hit['id'] for block in segment_blocks)
        # React SourceBlocks tests check named per-portion citation links and escaped text.
        api=client.get('/api/search',params={'q':'copper','text_type':'mixed'}).json()
        assert api['direct'][0]['text_type']=='mixed'


def test_whole_book_text_type_is_rejected_and_section_editor_exposes_type(tmp_path):
    lib,commentary,_,_=mixed_source(tmp_path)
    with pytest.raises(ValueError,match='whole book'):
        classify(lib,commentary['work_id'],'scripture')
    with TestClient(create_app(lib),base_url=ORIGIN) as client:
        book=tree(client.get('/api/ui/metadata/'+commentary['work_id'],params={'work':commentary['work_id']}))
        assert 'text_type' not in book['fields']
        section=tree(client.get('/api/ui/metadata/'+commentary['section_id'],params={'work':commentary['work_id']}))
        assert 'text_type' in section['fields']
        assert 'mixed' in section['text_types']


def test_section_scripture_bibliography_drives_display_type_and_citation(tmp_path):
    from test_citations import bib
    from test_scripture_citations import scripture_metadata
    source=docx(tmp_path/'books'/'Bible'/'Book.docx',[
        ('Heading1','Matthew 5:1–12'),'Copper blessed peacemakers.'])
    lib=seed(tmp_path/'books',[{'title':'Test Study Bible','author':'The Editors',
                              'paths':[source],'metadata':{'editors':['The Editors']}}])
    hit=lib.search('copper',engine='exact')['direct'][0]
    bib(lib,hit['section_id'],scripture_metadata(),origin='codex')
    lib.sync(semantic=False)
    found=lib.search('copper',engine='exact')['direct'][0]
    assert found['attribution']=='Scripture — NRSVue'
    assert found['text_type']=='scripture' and found['text_type_status']=='confirmed'
    assert all(b['attribution']=='Scripture — NRSVue' for b in lib.read(hit['id'],context=0)['blocks'])
    assert lib.cite(hit['id'])['ready']
