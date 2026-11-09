"""A source span cannot extend a scholar's credit into adjacent material."""
from __future__ import annotations

import copy
import json
import pytest

from book_library.passage_segments import validate_segments, segments_for_passage, segment_summary
from test_scripture_citations import segmented_source
from test_service import docx


def editorial(first, last, **patch):
    return {'first_block_id': first, 'last_block_id': last, 'text_type': 'editorial',
            'attribution': 'Unsigned editorial note',
            'bibliography': {'type': 'entry', 'title': 'Editorial note', 'authors': []}, **patch}


def test_segments_require_complete_ordered_nonoverlapping_source_coverage():
    rows = [{'id': 'a', 'text': 'First'}, {'id': 'blank', 'text': ' '},
            {'id': 'b', 'text': 'Second'}, {'id': 'c', 'text': 'Third'}]
    segments = [editorial('a', 'a'), editorial('b', 'c')]
    validate_segments(segments, rows)  # blank-only gaps do not invent content
    for invalid in ([editorial('a', 'b')],  # uncovered final text
                    [editorial('a', 'b'), editorial('b', 'c')],  # overlap
                    [editorial('b', 'c'), editorial('a', 'a')],  # reordered
                    [editorial('a', 'outside')],
                    [editorial('c', 'a')]):
        with pytest.raises(ValueError):
            validate_segments(invalid, rows)


def test_segment_shapes_and_scripture_identity_are_checked():
    rows = [{'id': 'a', 'text': 'First'}]
    for value in ([], {}, [editorial('a','a', text_type='something_else')],
                  [editorial('a','a', text_type='mixed')],
                  [editorial('a','a', text_type='scripture')],
                  [editorial('a','a', attribution='')],
                  [editorial('a','a', bibliography={'invented_field':'bad'})]):
        with pytest.raises(ValueError): validate_segments(value, rows)


def test_segments_work_with_sqlite_style_rows_and_preserve_evidence():
    rows = [{'data': json.dumps({'id':'a','text':'One'})},
            {'data': json.dumps({'id':'b','text':'Two'})}]
    event = {'id':'edit_example','status':'confirmed','origin':'user','evidence':'Inspected both blocks.',
             'value':[editorial('a','a'), editorial('b','b',text_type='reference')]}
    result = segments_for_passage('pid',{('pid','segments'):event},rows)
    assert result[0]['segment_id'] == 'a'
    assert result[0]['event'] == event
    assert [b['id'] for b in result[0]['blocks']] == ['a']
    assert segment_summary(result)['text_type'] == 'mixed'
    assert segment_summary(result)['text_types'] == ['editorial','reference']
    assert segments_for_passage('absent',{},rows) == []


def test_mixed_reading_retains_text_and_each_block_credit(tmp_path):
    lib, hit, segments = segmented_source(tmp_path)
    before = lib.read(hit['id'],context=0)
    lib.sync(semantic=False)
    after = lib.read(hit['id'],context=0)
    assert before['passage']['text'] == after['passage']['text']
    assert after['passage']['text_type'] == 'mixed'
    assert after['passage']['text_types'] == ['scripture','commentary']
    assert after['passage']['attribution_scope'] == 'segments'
    assert after['blocks'][0]['attribution'] == 'Scripture — NRSVue'
    assert after['blocks'][1]['text_type'] == 'scripture'
    assert after['blocks'][2]['attribution'] == 'Aaron M. Gale'
    assert after['blocks'][2]['text_type'] == 'commentary'
    assert after['blocks'][2]['segment_id'] == segments[1]['first_block_id']
    assert not any('contributor requires verification' in item.lower() for item in after['passage']['limitations'])


def test_segments_only_accept_passages_and_do_not_append_invalid_edits(tmp_path):
    lib, hit, segments = segmented_source(tmp_path)
    count = len(lib._curation())
    for target in (hit['work_id'],hit['section_id']):
        with pytest.raises(ValueError,match='passage'):
            lib.annotate(target,{'field':'segments','value':segments,'origin':'codex',
                                 'status':'confirmed','evidence':'Wrong target scope.'})
    invalid=copy.deepcopy(segments);invalid[-1]['last_block_id']='block_outside'
    with pytest.raises(ValueError):
        lib.annotate(hit['id'],{'field':'segments','value':invalid,'origin':'codex',
                               'status':'confirmed','evidence':'Outside source boundary.'})
    assert len(lib._curation()) == count


def test_user_segments_survive_codex_changes_and_renames(tmp_path):
    lib, hit, segments = segmented_source(tmp_path)
    corrected=copy.deepcopy(segments);corrected[1]['attribution']='User verified scholarly credit'
    lib.annotate(hit['id'],{'field':'segments','value':corrected,'origin':'user',
                           'status':'confirmed','evidence':'User checked the source.'})
    lib.annotate(hit['id'],{'field':'segments','value':segments,'origin':'codex',
                           'status':'confirmed','evidence':'Later automated pass must not replace correction.'})
    source=next(iter(lib._catalog()['files'].values()))['path']
    from pathlib import Path
    original=Path(source);renamed=original.with_name('Renamed.docx');original.rename(renamed)
    lib.sync(semantic=False);lib.sync(rebuild=True,semantic=False)
    read=lib.read(hit['id'],context=0)
    assert read['blocks'][2]['attribution']=='User verified scholarly credit'
    assert read['passage']['source_paths']==[str(renamed)]
    assert lib.status()['orphaned_curation_count']==0


def test_changed_text_orphans_segments_without_transferring_them(tmp_path):
    lib, hit, _ = segmented_source(tmp_path)
    source=next(iter(lib._catalog()['files'].values()))['path']
    from pathlib import Path
    docx(Path(source),[('Heading1','Matthew'),'Amber replacement passage.'])
    lib.sync(semantic=False)
    replacement=lib.search('amber replacement',engine='exact')['direct'][0]
    assert replacement['id']!=hit['id']
    assert replacement['text_type']=='unknown'
    assert not replacement['segments']
    assert hit['id'] in lib.status()['orphaned_curation']
    assert 'Aaron M. Gale' not in replacement['attribution']


def test_user_passage_attribution_blocks_conflicting_automatic_segments(tmp_path):
    lib,hit,segments=segmented_source(tmp_path)
    lib.annotate(hit['id'],{'field':'attribution','value':'User verified credit',
                           'origin':'user','status':'confirmed','evidence':'Scoped user correction.'})
    lib.sync(semantic=False)
    reading=lib.read(hit['id'],context=0)
    assert reading['passage']['attribution']=='User verified credit'
    assert reading['passage']['segments']==[]
    assert all(b['attribution']=='User verified credit' for b in reading['blocks'])
    assert any('user correction' in warning for warning in reading['passage']['limitations'])
    assert any(e['field']=='segments' for e in lib._curation())  # history remains
    # After explicit source review the user can approve the component model.
    lib.annotate(hit['id'],{'field':'segments','value':segments,'origin':'user',
                           'status':'confirmed','evidence':'Rechecked and approved source spans.'})
    lib.sync(semantic=False)
    assert lib.read(hit['id'],context=0)['passage']['text_type']=='mixed'


def test_user_override_citation_withholds_automatic_components_before_and_after_sync(tmp_path):
    lib,hit,segments=segmented_source(tmp_path)
    lib.annotate(hit['id'],{'field':'attribution','value':'User verified scoped credit',
                           'origin':'user','status':'confirmed','evidence':'Explicit source correction.'})
    for synchronize in (False,True):
        if synchronize:lib.sync(semantic=False)
        citation=lib.cite(hit['id'])
        assert citation['attribution']=='User verified scoped credit'
        assert not citation['ready'] and citation['needs_review']
        assert 'component.user_correction' in citation['review_fields']
        assert any('user correction' in warning for warning in citation['warnings'])
        assert not citation.get('component_citations')
        with pytest.raises(ValueError,match='withheld'):
            lib.cite(hit['id'],segment_id=segments[0]['first_block_id'])


def test_scripture_bibliography_cannot_masquerade_as_commentary_segment():
    from test_scripture_citations import scripture_metadata
    rows=[{'id':'a','text':'One'}]
    with pytest.raises(ValueError,match='only to Scripture'):
        validate_segments([editorial('a','a',text_type='commentary',bibliography=scripture_metadata())],rows)


def test_blank_segment_endpoints_are_rejected_before_durable_annotation(tmp_path):
    from test_service import seed
    source=docx(tmp_path/'books'/'Mixed'/'Book.docx',[
        ('Heading1','Annotated passage'),'Copper first component.','\n','Violet second component.'])
    lib=seed(tmp_path/'books',[{'title':'An Annotated Bible','author':'Volume Editor',
                               'paths':[source],'metadata':{'editors':['Volume Editor']}}])
    hit=lib.search('copper',engine='exact')['direct'][0]
    with lib._db() as db:
        passage=db.execute('SELECT * FROM passages WHERE id=?',(hit['id'],)).fetchone()
        rows=db.execute('SELECT id,text FROM blocks WHERE work_id=? AND ordinal BETWEEN ? AND ? ORDER BY ordinal',
                        (hit['work_id'],passage['first_ordinal'],passage['last_ordinal'])).fetchall()
    ids={row['text']:row['id'] for row in rows}
    blank=next(row['id'] for row in rows if not row['text'].strip())
    first=rows[0]['id'];last=rows[-1]['id']
    before=len(lib._curation())
    for segments in ([editorial(first,blank),editorial(last,last)],
                     [editorial(first,ids['Copper first component.']),editorial(blank,last)]):
        with pytest.raises(ValueError,match='nonblank'):
            lib.annotate(hit['id'],{'field':'segments','value':segments,'origin':'codex',
                                   'status':'confirmed','evidence':'Invalid blank boundary in fixture.'})
    assert len(lib._curation())==before
    lib.annotate(hit['id'],{'field':'segments',
        'value':[editorial(first,ids['Copper first component.']),editorial(last,last)],
        'origin':'codex','status':'confirmed','evidence':'Nonblank boundaries, with a blank-only gap.'})
    lib.sync(semantic=False)
    assert len(lib.read(hit['id'],context=0)['passage']['segments'])==2
