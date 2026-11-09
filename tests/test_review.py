"""Independent regressions for identity, attribution, and bounded reading."""
import json
from pathlib import Path
import pytest
from test_service import docx, seed, annotate
from book_library.service import Library


def test_manifest_after_initial_discovery_enriches_same_work(tmp_path):
    root=tmp_path/'books'; source=docx(root/'Author - Book'/'Book.docx',['Sapphire late acquisition.'])
    lib=Library(root);lib.sync(); wid=lib.books()[0]['id']
    (root/'.catalog').mkdir()
    (root/'.catalog/bookshare-123.json').write_text(json.dumps({'books':[{'bookshare_id':'123','title':'Verified Book','author':'Verified Author','folder':str(source.parent),'files':[{'path':str(source)}]}]}))
    lib.sync()
    assert len(lib._catalog()['works'])==1
    assert lib.books()[0]['id']==wid
    assert lib.books()[0]['title']=='Verified Book'
    assert len(lib._catalog()['acquisitions'])==1
    assert next(iter(lib._catalog()['acquisitions'].values()))['stage']=='text_ready'


def test_folder_rename_with_catalog_refresh_preserves_curation(tmp_path):
    root=tmp_path/'books'; source=docx(root/'Old Folder'/'Book.docx',['Azure renamed evidence.'])
    lib=seed(root,[{'title':'Original','paths':[source],'bookshare_id':'321'}]);wid=lib.books()[0]['id']
    annotate(lib,wid,'Editorial title',field='title');lib.sync()
    newdir=root/'New Folder';source.parent.rename(newdir);newsource=newdir/source.name
    cat=json.loads((root/'.catalog/library.json').read_text());cat['books'][0]['folder']=str(newdir);cat['books'][0]['files'][0]['path']=str(newsource)
    (root/'.catalog/library.json').write_text(json.dumps(cat));lib.sync()
    assert len(lib._catalog()['works'])==1
    assert lib.books()[0]['id']==wid
    assert lib.search('azure renamed')['direct'][0]['title']=='Editorial title'
    assert str(source) in lib.book(wid)['files'][0]['previous_paths']


def test_repeated_heading_insertion_does_not_move_contributor(tmp_path):
    root=tmp_path/'books'; source=docx(root/'Anthology'/'Book.docx', [('Heading1','Perspective'),'Amber original author statement.',('Heading1','Perspective'),'Violet separate author statement.'])
    lib=seed(root,[{'title':'Anthology','author':'Volume Editor','paths':[source]}]);hit=lib.search('amber original')['direct'][0]
    annotate(lib,hit['section_id'],'Actual Author',field='attribution');lib.sync()
    docx(source,[('Heading1','Perspective'),'New sapphire prefatory statement.',('Heading1','Perspective'),'Amber original author statement.',('Heading1','Perspective'),'Violet separate author statement.'])
    lib.sync()
    assert lib.search('amber original')['direct'][0]['attribution']=='Actual Author'
    assert lib.search('sapphire prefatory')['direct'][0]['attribution']!='Actual Author'


def test_verified_section_author_is_searchable_and_filterable(tmp_path):
    root=tmp_path/'books';source=docx(root/'Anthology'/'Book.docx',[('Heading1','River'),'Cobalt waters carry memory.'])
    lib=seed(root,[{'title':'Anthology','author':'Volume Editor','paths':[source]}]);hit=lib.search('cobalt')['direct'][0]
    annotate(lib,hit['section_id'],'Actual Poet',field='attribution');lib.sync()
    assert lib.search('Actual Poet')['direct'][0]['attribution']=='Actual Poet'
    assert lib.search('cobalt',filters={'author':'Actual Poet'})['direct'][0]['attribution']=='Actual Poet'


def test_large_source_block_has_bounded_search_and_continuable_read(tmp_path):
    root=tmp_path/'books';text='Sapphire text with faithful line breaks.\n'*7000
    source=docx(root/'Large'/'Book.docx',[('Heading1',text)])
    lib=seed(root,[{'title':'Large','paths':[source]}]);hit=lib.search('sapphire')['direct'][0]
    assert len(json.dumps(hit))<10000
    read=lib.read(hit['id'],context=0)
    assert len(json.dumps(read))<100000
    assert read.get('next_offset')
    later=lib.read(hit['id'],context=0,offset=read['next_offset'])
    assert later['offset']==read['next_offset']


def test_invalid_annotation_cannot_poison_future_indexing(tmp_path):
    root=tmp_path/'books';source=docx(root/'Book'/'Book.docx',['Bronze valid text.'])
    lib=seed(root,[{'title':'Book','paths':[source]}]);wid=lib.books()[0]['id']
    with pytest.raises(ValueError): annotate(lib,wid,[],field='title')
    assert lib.sync()['changed'] is False


def test_ambiguous_repeated_sections_fail_closed_and_report_orphan(tmp_path):
    root=tmp_path/'books';source=docx(root/'Book'/'Book.docx',[('Heading1','Repeat'),'Identical text.',('Heading1','Repeat'),'Identical text.'])
    lib=seed(root,[{'title':'Book','paths':[source]}]);hit=lib.search('identical')['direct'][0]
    annotate(lib,hit['section_id'],'Curated Poet',field='attribution');lib.sync()
    docx(source,[('Heading1','Repeat'),'Identical text.',('Heading1','Repeat'),'Identical text.','File changed elsewhere.']);lib.sync()
    assert lib.status()['orphaned_curation_count']==1
    assert all(h['attribution']!='Curated Poet' for h in lib.search('identical')['direct'])


def test_section_level_browse_filters_match_section_search(tmp_path):
    root=tmp_path/'books';source=docx(root/'Book'/'Book.docx',[('Heading1','River'),'Sapphire water.'])
    lib=seed(root,[{'title':'Book','paths':[source]}]);hit=lib.search('sapphire')['direct'][0]
    annotate(lib,hit['section_id'],{'subjects':['ecology'],'forms':['poem']});lib.sync()
    assert [b['id'] for b in lib.books(facet={'subject':'ecology'})]==[hit['work_id']]
    assert [b['id'] for b in lib.books(facet={'form':'poem'})]==[hit['work_id']]


def test_missing_extraction_cache_regenerates_without_rehashing_unchanged_source(tmp_path,monkeypatch):
    import book_library.service as service
    root=tmp_path/'books';source=docx(root/'Book'/'Book.docx',['Sapphire recovery evidence.'])
    lib=seed(root,[{'title':'Book','paths':[source]}]);hit=lib.search('sapphire')['direct'][0]
    record=next(iter(lib._catalog()['files'].values()));(lib.state/'extractions'/record['cache']).unlink()
    original_digest=service.digest
    def guarded_digest(path):
        assert Path(path).suffix!='.docx','Unchanged source hash should be reused'
        return original_digest(path)
    monkeypatch.setattr(service,'digest',guarded_digest)
    assert lib.sync()['extracted']==1
    assert lib.search('sapphire')['direct'][0]['id']==hit['id']


def test_corrupt_cache_repairs_on_rebuild_and_failure_is_isolated(tmp_path,monkeypatch):
    import book_library.extract as extractor
    root=tmp_path/'books';one=docx(root/'One'/'One.docx',['Amber first evidence.']);two=docx(root/'Two'/'Two.docx',['Violet second evidence.'])
    lib=seed(root,[{'title':'One','paths':[one]},{'title':'Two','paths':[two]}])
    record=next(f for f in lib._catalog()['files'].values() if f['path']==str(one));cache=lib.state/'extractions'/record['cache'];cache.write_bytes(b'broken gzip')
    assert lib.sync(rebuild=True)['extracted']==1
    assert lib.search('amber')['direct'] and lib.search('violet')['direct']
    cache.write_bytes(b'broken again');original=extractor.extract_file
    def failed(path):
        if path==one:raise ValueError('Simulated source decoding failure')
        return original(path)
    monkeypatch.setattr(extractor,'extract_file',failed)
    result=lib.sync(rebuild=True)
    assert len(result['errors'])==1
    assert lib.search('violet')['direct']
    assert not lib.search('amber')['direct']
    monkeypatch.setattr(extractor,'extract_file',original)
    lib.sync()
    assert lib.search('amber')['direct']
