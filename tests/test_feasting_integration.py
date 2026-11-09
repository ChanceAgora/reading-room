"""Synthetic Word packages (invented prose, source-style contributor names): source bylines, shared endnotes, and durable corrections."""
import json
from xml.sax.saxutils import escape
from zipfile import ZipFile

from book_library.service import Library
from book_library.storage import atomic_json
from test_service import W, docx, seed


def package(root, *, with_links=True):
    path = docx(root/'Commentary'/'part1.docx', [
        ('Heading1', 'Matthew 5:1–12'), ('Heading2', 'Theological Perspective'),
        'Amber theology discusses the Beatitudes and the surrounding Gospel narrative in substantial detail for careful teaching. REFERENCE',
        'MARCIA Y. RIGGS', ('Heading2', 'Homiletical Perspective'),
        'Copper homiletics discusses the Beatitudes and public proclamation in substantial detail, with a different contributor and perspective.',
        'RONALD J. ALLEN', '1. Turquoise theological note attributed through reciprocal links.',
        '2. Magenta shared note without an identifiable owner.',
        ('Heading1', 'Contributors'), 'Marcia Y. Riggs, Professor of Ethics, A Seminary',
        'Ronald J. Allen, Professor of Preaching, Another Seminary',
    ])
    if with_links:
        with ZipFile(path) as z:
            members={name:z.read(name) for name in z.namelist()}
        source=members['word/document.xml'].decode()
        source=source.replace('REFERENCE</w:t></w:r>', '</w:t></w:r><w:bookmarkStart w:id="10" w:name="chapter_fn1a"/><w:hyperlink w:anchor="chapter_fn1"><w:r><w:t>1</w:t></w:r></w:hyperlink><w:bookmarkEnd w:id="10"/>')
        source=source.replace('<w:r><w:t xml:space="preserve">1. Turquoise', '<w:bookmarkStart w:id="11" w:name="chapter_fn1"/><w:hyperlink w:anchor="chapter_fn1a"><w:r><w:t>1.</w:t></w:r></w:hyperlink><w:bookmarkEnd w:id="11"/><w:r><w:t xml:space="preserve"> Turquoise')
        members['word/document.xml']=source.encode()
        with ZipFile(path,'w') as z:
            for name,value in members.items():z.writestr(name,value)
    return path


def setup(tmp_path):
    root=tmp_path/'books'; path=package(root)
    return seed(root,[{'title':'Feasting on the Word: Test Volume','author':'Volume Editors','paths':[path],'metadata':{'editors':['Volume Editors']}}]),path


def hit(lib,query):
    return lib.search(query,engine='exact',connections=0)['direct'][0]


def test_byline_and_reciprocal_notes_reach_search_read_and_citation(tmp_path):
    lib,path=setup(tmp_path)
    theology=hit(lib,'amber theology'); homily=hit(lib,'copper homiletics')
    assert theology['attribution']=='Marcia Y. Riggs'
    assert homily['attribution']=='Ronald J. Allen'
    note=hit(lib,'turquoise theological')
    assert note['section_id']==theology['section_id']
    assert note['attribution']=='Marcia Y. Riggs'
    assert lib.read(note['id'],context=0)['blocks'][0]['kind']=='note'
    unowned=hit(lib,'magenta shared')
    assert unowned['section_id'] not in (theology['section_id'],homily['section_id'])
    assert 'unverified' in unowned['attribution'].lower()
    assert 'Contributor unverified' not in theology['attribution']
    citation=lib.cite(theology['id'])
    assert citation['full_note'].startswith('Marcia Y. Riggs, “Theological Perspective,”')
    assert citation['locator']['value']=='Matthew 5:1–12 / Theological Perspective'
    assert 'section.name_order' in citation['review_fields']
    assert citation['provenance']['section.authors']['origin']=='source_byline'
    before=path.read_bytes()
    lib.sync(rebuild=True)
    assert hit(lib,'amber theology')['section_id']==theology['section_id']
    assert hit(lib,'turquoise theological')['attribution']=='Marcia Y. Riggs'
    assert path.read_bytes()==before


def test_contributor_correction_and_structured_name_override_survive_rebuild(tmp_path):
    lib,_=setup(tmp_path); theology=hit(lib,'amber theology')
    lib.annotate(theology['section_id'],{'field':'bibliography','value':{'authors':[{'given':'Marcia Y.','family':'Riggs'}]},'origin':'user','status':'confirmed','evidence':'Checked source name structure.'})
    lib.sync(rebuild=True)
    citation=lib.cite(hit(lib,'amber theology')['id'])
    assert citation['bibliography'].startswith('Riggs, Marcia Y.')
    assert 'section.name_order' not in citation['review_fields']
    assert citation['provenance']['section.title']['origin']=='source_byline'
    lib.annotate(theology['section_id'],{'field':'attribution','value':'User correction','origin':'user','status':'confirmed','evidence':'Explicit editorial correction.'})
    lib.sync(rebuild=True)
    assert hit(lib,'amber theology')['attribution']=='User correction'
    assert hit(lib,'turquoise theological')['attribution']=='User correction'


def test_derived_index_upgrade_reuses_extraction_and_preserves_identity(tmp_path):
    lib,_=setup(tmp_path); before=hit(lib,'amber theology')
    active=lib._active();active.pop('index_version');atomic_json(lib.state/'current.json',active)
    assert lib.status()['index_pending']
    result=lib.sync(semantic=False)
    assert result['changed'] and result['extracted']==0
    assert hit(lib,'amber theology')['section_id']==before['section_id']
    assert not lib.status()['index_pending']
