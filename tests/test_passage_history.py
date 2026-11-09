"""Saved excerpts keep their exact extent when normalized boundaries change."""
import os
import pytest

from book_library import structure
from test_citations import bib, page, verified_book
from test_service import docx, seed


def resegmented_source(tmp_path, monkeypatch):
    source = docx(tmp_path / 'books' / 'Reader' / 'reader.docx', [
        ('Heading1', 'An old broad heading'),
        'Copper witness belongs to the old saved excerpt.',
        'A newly recovered contribution',
        'Violet witness also belongs to the old saved excerpt.',
        ('Heading1', 'A neighbor'),
        'Amber witness was never in that excerpt.',
    ])
    lib = seed(tmp_path / 'books', [{'title': 'An Edited Reader', 'author': 'Volume Editor',
                                    'metadata': {'editors': ['Volume Editor']}, 'paths': [source]}])
    old = lib.search('copper witness', engine='exact')['direct'][0]
    before = lib.read(old['id'], context=0)
    verified_book(lib, old, authors=[], editors=[{'given': 'Volume', 'family': 'Editor'}])
    correction = bib(lib, old['id'], {'type': 'chapter', 'title': 'Only this saved extent',
                                     'authors': [{'given': 'Exact', 'family': 'Contributor'}],
                                     'locator': page('73–74')})
    lib.sync(semantic=False)
    prepare = structure.prepare_work

    def recover_heading(lib, work, files, extractions):
        # This models a new analyzer recovering a source-supported boundary.
        # Physical source bytes, extraction cache, and block anchors stay fixed.
        for extraction in extractions.values():
            for block in extraction['blocks']:
                if block['text'] == 'A newly recovered contribution':
                    block.update(kind='heading', level=1, heading_path=[block['text']])
        return prepare(lib, work, files, extractions)

    monkeypatch.setattr(structure, 'prepare_work', recover_heading)
    lib.sync(rebuild=True, semantic=False)
    return lib, old, before, correction, source


def test_old_link_retains_complete_source_extent_and_narrow_correction_after_split(tmp_path, monkeypatch):
    lib, old, before, correction, _ = resegmented_source(tmp_path, monkeypatch)
    copper = lib.search('copper witness', engine='exact')['direct'][0]
    violet = lib.search('violet witness', engine='exact')['direct'][0]
    assert copper['id'] != old['id'] != violet['id']
    assert copper['section_id'] != violet['section_id']
    restored = lib.read(old['id'], context=8)
    assert restored['passage']['text'] == before['passage']['text']
    assert [b['id'] for b in restored['blocks']] == [b['id'] for b in before['blocks']]
    assert all(b['selected'] for b in restored['blocks'])
    assert 'Amber witness' not in restored['passage']['text']
    assert restored['previous'] is None and restored['next'] is None
    assert restored['passage']['attribution'] == 'Exact Contributor'
    assert all(b['attribution'] == 'Exact Contributor' for b in restored['blocks'])
    old_citation = lib.cite(old['id'])
    assert old_citation['full_note'].startswith('Exact Contributor, “Only this saved extent,”')
    assert old_citation['locator']['value'] == '73–74'
    assert old_citation['metadata_scope'] == 'passage'
    assert old_citation['provenance']['section.authors']['annotation_id'] == correction['id']
    for replacement in (copper, violet):
        assert 'Exact Contributor' not in replacement['attribution']
        assert 'Exact Contributor' not in lib.cite(replacement['id'], page())['full_note']
        assert 'Exact Contributor' not in lib.cite_unit(replacement['unit_id'], page())['full_note']
    assert any(event['id'] == correction['id'] for event in lib._curation())
    status = lib.status()
    assert status['historical_passage_curation_count'] == 1
    assert old['id'] not in status['orphaned_curation']
    # TEMP aliases leave the published retrieval index and neighboring credits intact.
    with lib._db() as db:
        assert db.execute('SELECT id FROM passages WHERE id=?', (old['id'],)).fetchone() is None


def test_changed_source_keeps_old_correction_unresolved_instead_of_attaching_neighbor(tmp_path, monkeypatch):
    lib, old, before, correction, source = resegmented_source(tmp_path, monkeypatch)
    docx(source, [('Heading1', 'An old broad heading'),
                  'Copper witness now belongs to a changed source version.',
                  'A newly recovered contribution', 'Replacement violet witness.',
                  ('Heading1', 'A neighbor'), 'Amber witness remains a neighbor.'])
    for action in (lib.read, lib.cite):
        with pytest.raises(ValueError, match='unavailable.*source version'):
            action(old['id'])
    lib.sync(semantic=False)
    for action in (lib.read, lib.cite):
        with pytest.raises(ValueError, match='unavailable.*source version'):
            action(old['id'])
    replacements = lib.search('witness', engine='exact', limit=30)['direct']
    assert replacements
    assert all('Exact Contributor' not in result['attribution'] for result in replacements)
    assert old['id'] in lib.status()['orphaned_curation']
    assert any(event['id'] == correction['id'] for event in lib._curation())


def test_historical_read_checks_bytes_even_if_size_and_mtime_match(tmp_path, monkeypatch):
    lib, old, _, _, source = resegmented_source(tmp_path, monkeypatch)
    stat = source.stat()
    changed = bytearray(source.read_bytes()); changed[-1] ^= 1
    source.write_bytes(changed)
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert source.stat().st_size == stat.st_size
    assert source.stat().st_mtime_ns == stat.st_mtime_ns
    for action in (lib.read, lib.cite):
        with pytest.raises(ValueError, match='unavailable.*source version'):
            action(old['id'])
