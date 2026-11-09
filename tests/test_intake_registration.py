import copy
import json
import shutil
from pathlib import Path
from zipfile import ZipFile

import pytest

from book_library.intake_registration import grounded_inspection_leads, register_intake
from book_library.service import Library
from book_library.storage import digest
from test_service import docx, seed


def test_generic_registration_is_not_paid_or_verified_and_is_idempotent(tmp_path):
    path = docx(tmp_path / 'Essay' / 'Essay.docx', [('Heading1', 'Introduction'), 'An introduction to a new essay.'])
    lib = Library(tmp_path)
    record = register_intake(lib, path, {'provider': 'publisher', 'metadata': {'title': 'The Essay', 'author': 'Candidate Writer', 'publication_year': '2026'}})
    assert not lib._active() and not (lib.state / 'ledger.jsonl').exists()
    assert register_intake(lib, path)['identity'] == record['identity']
    lib.sync(semantic=False)
    catalog = lib._catalog()
    work = next(iter(catalog['works'].values()))
    assert work['title'] == 'The Essay' and work['contributors'] == []
    assert catalog['acquisitions'][record['id']]['provider'] == 'publisher'
    assert not (lib.state / 'curation.jsonl').exists()
    assert not (lib.state / 'intakes').exists()
    context = lib.review_context(work['id'])
    assert context['target']['source_origin'] == 'publisher'
    year = next(f for f in context['fields'] if f['key'] == 'bibliography.year')
    assert year['status'] == 'candidate'


def test_split_parts_use_explicit_order_and_all_bytes_survive(tmp_path):
    first = docx(tmp_path / 'Split' / 'part10.docx', ['Last part.'])
    second = docx(tmp_path / 'Split' / 'part2.docx', ['First part.'])
    before = {p: digest(p) for p in (first, second)}
    lib = Library(tmp_path)
    record = register_intake(lib, first.parent, {'files': [{'path': str(first), 'sequence': 10}, {'path': str(second), 'sequence': 2}]})
    assert [f['path'] for f in record['files']] == [str(second), str(first)]
    lib.sync(semantic=False)
    assert len(lib._catalog()['works']) == 1
    assert {p: digest(p) for p in before} == before


def test_identical_complete_copy_reuses_identity_without_deleting_files(tmp_path):
    path = docx(tmp_path / 'Original' / 'Book.docx', [('Heading1', 'Chapter'), 'The same exact copy.'])
    lib = seed(tmp_path, [{'title': 'Existing Book', 'paths': [path]}])
    work_id = next(iter(lib._catalog()['works']))
    duplicate = tmp_path / 'New Download' / 'Other name.docx'
    duplicate.parent.mkdir()
    shutil.copyfile(path, duplicate)
    record = register_intake(lib, duplicate)
    assert record['existing_work_ids'] == [work_id]
    assert record['files'][0]['path'] == str(path)
    lib.sync(semantic=False)
    assert len(lib._catalog()['works']) == 1 and duplicate.exists()
    assert digest(duplicate) == digest(path)
    docx(duplicate, ['Different contents now.'])
    assert str(duplicate) in lib._inventory()


def test_metadata_duplicates_stay_distinct_and_are_flagged(tmp_path):
    path = docx(tmp_path / 'First' / 'Book.docx', ['First edition content.'])
    lib = seed(tmp_path, [{'title': 'Shared Title', 'paths': [path]}])
    other = docx(tmp_path / 'Second' / 'Book.docx', ['Revised content.'])
    record = register_intake(lib, other, {'metadata': {'title': 'Shared Title', 'edition': 'Second edition'}})
    assert len(record['duplicate_candidates']) == 1
    lib.sync(semantic=False)
    assert len(lib._catalog()['works']) == 2


def test_bookshare_archive_checks_exact_member_coverage_and_hashes(tmp_path):
    root = tmp_path / 'books'
    a = docx(root / 'Parts' / 'A.docx', ['First part.'])
    b = docx(root / 'Parts' / 'B.docx', ['Last part.'])
    archive = tmp_path / 'Original.zip'
    with ZipFile(archive, 'w') as package:
        package.write(a, 'original-1.docx'); package.write(b, 'original-2.docx')
    lib = Library(root)
    ctx = {'provider': 'bookshare', 'provider_id': '123', 'provenance': {'archive_path': str(archive)},
           'files': [{'path': str(a), 'original_zip_member': 'original-1.docx'}, {'path': str(b), 'original_zip_member': 'original-2.docx'}]}
    bad = copy.deepcopy(ctx); bad['files'].pop()
    with pytest.raises(ValueError, match='every book member'):
        register_intake(lib, a.parent, bad)
    record = register_intake(lib, a.parent, ctx)
    assert record['validation']['retained_source_checked']
    assert record['provenance']['archive_sha256'] == digest(archive)
    lib.sync(semantic=False)
    assert lib._catalog()['acquisitions'][record['id']]['provider_id'] == '123'


def test_direct_docx_source_is_supported_and_mismatches_are_rejected(tmp_path):
    original = docx(tmp_path / 'download.docx', ['The original.'])
    root = tmp_path / 'books'; placed = root / 'Book' / 'Book.docx'
    placed.parent.mkdir(parents=True); shutil.copyfile(original, placed)
    lib = Library(root)
    bad = {'provenance': {'source_file': str(original), 'source_sha256': 'wrong'}}
    with pytest.raises(ValueError, match='byte-identical'):
        register_intake(lib, placed, bad)
    assert register_intake(lib, placed, {'provenance': {'source_file': str(original)}})['validation']['retained_source_checked']


def test_registration_rejects_outside_paths_symlinks_unsupported_and_wrong_hash(tmp_path):
    root = tmp_path / 'books'; root.mkdir()
    outside = docx(tmp_path / 'outside.docx', ['Outside.'])
    lib = Library(root)
    with pytest.raises(ValueError, match='inside the library'):
        register_intake(lib, outside)
    linked = root / 'linked.docx'; linked.symlink_to(outside)
    with pytest.raises(ValueError): register_intake(lib, linked)
    pdf = root / 'Book.pdf'; pdf.write_bytes(b'%PDF')
    with pytest.raises(ValueError): register_intake(lib, pdf)
    path = docx(root / 'Book' / 'Book.docx', ['Valid.'])
    with pytest.raises(ValueError, match='fingerprint'):
        register_intake(lib, path, {'files': [{'path': str(path), 'sha256': 'wrong'}]})


def test_legacy_null_provider_ids_do_not_join_unrelated_file_lists(tmp_path):
    a = docx(tmp_path / 'A' / 'A.docx', ['One.'])
    b = docx(tmp_path / 'B' / 'B.docx', ['Two.'])
    manifests = tmp_path / '.catalog'; manifests.mkdir()
    (manifests / 'generic.json').write_text(json.dumps({'books': [
        {'title': 'A', 'folder': str(a.parent)}, {'title': 'B', 'folder': str(b.parent)}],
        'files': [{'path': str(a)}, {'path': str(b)}]}))
    lib = Library(tmp_path); lib.sync(semantic=False)
    assert len(lib._catalog()['works']) == 2
    assert lib._catalog()['acquisitions'] == {}


def test_inspection_leads_require_exact_file_hash_location_and_quote(tmp_path):
    path = docx(tmp_path / 'Book' / 'Book.docx', [('Heading1', 'Introduction'), 'An introduction.'])
    lib = seed(tmp_path, [{'title': 'Book', 'paths': [path]}]); catalog = lib._catalog()
    work_id = next(iter(catalog['works'])); context = lib.review_context(work_id)
    source = next(e for e in context['evidence'] if e['kind'] == 'heading')
    file = next(iter(catalog['files'].values()))
    hint = {'path': str(path), 'sha256': file['sha256'], 'locator': source['locator'], 'quote': 'Introduction', 'field': 'title', 'value': 'Introduction'}
    metadata = {'acquisition_context': {'inspection_evidence': [hint]}}
    leads = grounded_inspection_leads(metadata, [file], context['evidence'])
    assert leads[0]['source_id'] == source['id'] and 'path' not in leads[0]
    hint['sha256'] = 'stale'
    assert grounded_inspection_leads(metadata, [file], context['evidence']) == []


def test_structured_roles_stay_separate_imported_candidates(tmp_path):
    path = docx(tmp_path / 'Book' / 'Book.docx', ['A translated collection.'])
    lib = Library(tmp_path)
    author = {'given': 'Jane', 'family': 'Writer', 'suffix': 'Jr.'}
    register_intake(lib, path, {'metadata': {'title': 'Collection', 'authors': [author], 'editors': ['Pat Editor'], 'translators': ['Alex Translator']}})
    lib.sync(semantic=False)
    work = next(iter(lib._catalog()['works'].values()))
    assert [(p['name'], p['role']) for p in work['contributors']] == [('Jane Writer, Jr.', 'author'), ('Pat Editor', 'editor'), ('Alex Translator', 'translator')]
    fields = {f['key']: f for f in lib.review_context(work['id'])['fields']}
    assert fields['bibliography.authors']['value'] == [author]
    assert fields['bibliography.authors']['status'] == 'candidate'


@pytest.mark.parametrize('metadata', [{'title': {'wrong': 'shape'}}, {'editors': 'A Person'}, {'publication_year': True}, {'source_url': 'javascript:alert(1)'}])
def test_malformed_context_cannot_poison_later_sync(tmp_path, metadata):
    path = docx(tmp_path / 'Book' / 'Book.docx', ['Healthy text.'])
    lib = Library(tmp_path)
    with pytest.raises(ValueError): register_intake(lib, path, {'metadata': metadata})
    assert not list((lib.state / 'acquisitions').glob('*.json'))
    lib.sync(semantic=False)
    assert len(lib._catalog()['works']) == 1


def test_changed_context_is_not_silently_discarded(tmp_path):
    path = docx(tmp_path / 'Book' / 'Book.docx', ['Healthy text.'])
    lib = Library(tmp_path)
    record = register_intake(lib, path, {'metadata': {'title': 'First supplied title'}})
    with pytest.raises(ValueError, match='different information'):
        register_intake(lib, path, {'metadata': {'title': 'Corrected supplied title'}})
    assert json.loads((lib.state / 'acquisitions' / (record['id'] + '.json')).read_text()) == record


def test_existing_bookshare_origin_survives_context_free_intake(tmp_path):
    path = docx(tmp_path / 'Book' / 'Book.docx', ['Existing Bookshare copy.'])
    lib = seed(tmp_path, [{'title': 'Book', 'bookshare_id': '123', 'paths': [path]}])
    record = register_intake(lib, path)
    assert record['provider'] == 'bookshare' and str(record['provider_id']) == '123'
    lib.sync(semantic=False)
    work_id = next(iter(lib._catalog()['works']))
    assert lib.review_context(work_id)['target']['source_origin'] == 'Bookshare accessible export'


def test_generic_epub_registers_and_indexes_without_legacy_manifest(tmp_path):
    path = tmp_path / 'Publisher' / 'Book.epub'; path.parent.mkdir()
    with ZipFile(path, 'w') as package:
        package.writestr('mimetype', 'application/epub+zip')
        package.writestr('META-INF/container.xml', '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="package.opf"/></rootfiles></container>')
        package.writestr('package.opf', '<package xmlns="http://www.idpf.org/2007/opf"><manifest><item id="body" href="body.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="body"/></spine></package>')
        package.writestr('body.xhtml', '<html xmlns="http://www.w3.org/1999/xhtml"><body><h1>Introduction</h1><p>Copper birds in an EPUB introduction.</p></body></html>')
    lib = Library(tmp_path); before = digest(path)
    record = register_intake(lib, path, {'provider': 'publisher', 'metadata': {'title': 'Publisher EPUB'}})
    lib.sync(semantic=False)
    assert lib.search('Copper birds', engine='exact')['direct']
    assert record['files'][0]['format'] == 'epub' and digest(path) == before
    assert not (tmp_path / '.catalog').exists()


def test_adjacent_unrelated_files_cannot_be_silently_registered_as_one_book(tmp_path):
    a = docx(tmp_path / 'Downloads' / 'First.docx', ['First unrelated book.'])
    b = docx(tmp_path / 'Downloads' / 'Second.docx', ['Second unrelated book.'])
    lib = Library(tmp_path)
    with pytest.raises(ValueError, match='Unselected book files'):
        register_intake(lib, a, {'metadata': {'title': 'First book'}})
    assert not list((lib.state / 'acquisitions').glob('*.json'))
    assert a.exists() and b.exists()


def test_changed_alias_with_restored_size_and_mtime_is_discovered(tmp_path):
    import os
    a = docx(tmp_path / 'Original' / 'Book.docx', ['Alpha text.'])
    lib = seed(tmp_path, [{'title': 'Original', 'paths': [a]}])
    b = tmp_path / 'Duplicate' / 'Book.docx'; b.parent.mkdir(); shutil.copyfile(a, b)
    register_intake(lib, b)
    old = b.stat()
    replacement = docx(tmp_path / 'replacement.docx', ['Omega text.'])
    assert replacement.stat().st_size == old.st_size
    os.replace(replacement, b); os.utime(b, ns=(old.st_atime_ns, old.st_mtime_ns))
    assert digest(a) != digest(b)
    assert str(b) in lib._inventory()


def test_standalone_file_does_not_absorb_or_reject_books_in_child_folders(tmp_path):
    standalone = docx(tmp_path / 'Standalone.docx', ['A standalone book.'])
    other = docx(tmp_path / 'Other' / 'Book.docx', ['A different book in its own folder.'])
    lib = Library(tmp_path)
    record = register_intake(lib, standalone)
    assert [item['path'] for item in record['files']] == [str(standalone)]
    lib.sync(semantic=False)
    catalog = lib._catalog()
    files = {item['path']: item for item in catalog['files'].values()}
    assert files[str(standalone)]['work_id'] != files[str(other)]['work_id']
