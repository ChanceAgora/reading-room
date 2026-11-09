"""Exercise real extracted books through citation forms, exports and the CLI.

All source packages and durable records live under pytest's temporary directory.
These are interface checks, not a replacement for manual assistive-technology QA.
"""
from __future__ import annotations

import json
import subprocess
import sys
from xml.sax.saxutils import escape
from zipfile import ZipFile

from fastapi.testclient import TestClient
import pytest

from book_library.service import Library
from book_library.web import create_app
from test_citations import bib, page, verified_book
from test_service import docx, seed


ORIGIN = "http://127.0.0.1:8765"
KEYS = ("full_note", "short_note", "bibliography")
TITLE = "The Shared Classroom: Learning Together"


@pytest.fixture(params=["docx", "epub"])
def source_library(tmp_path, request):
    root = tmp_path / "books"
    root.mkdir()
    if request.param == "docx":
        source = docx(root / "Classroom" / "Classroom.docx", [
            ("Heading1", "Title and Publication"),
            TITLE, "Jane Doe", "Example Press, 2024",
            ("Heading1", "Learning in Community"),
            "Copper birds gather near the water.",
        ])
        library = seed(root, [{"title": TITLE, "author": "Jane Doe", "paths": [source]}])
    else:
        source = root / "Classroom.epub"
        with ZipFile(source, "w") as archive:
            archive.writestr("mimetype", "application/epub+zip")
            archive.writestr("META-INF/container.xml", '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="EPUB/book.opf" media-type="application/oebps-package+xml"/></rootfiles></container>')
            archive.writestr("EPUB/book.opf", '<package xmlns="http://www.idpf.org/2007/opf" version="3.0"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>' + escape(TITLE) + '</dc:title><dc:creator>Jane Doe</dc:creator><dc:publisher>Example Press</dc:publisher><dc:date>2024</dc:date></metadata><manifest><item id="front" href="front.xhtml" media-type="application/xhtml+xml"/><item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="front"/><itemref idref="chapter"/></spine></package>')
            archive.writestr("EPUB/front.xhtml", '<html xmlns="http://www.w3.org/1999/xhtml"><body><h1>Title and Publication</h1><p>' + escape(TITLE) + '</p><p>Jane Doe</p><p>Example Press, 2024</p></body></html>')
            archive.writestr("EPUB/chapter.xhtml", '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><body><h1>Learning in Community</h1><span epub:type="pagebreak" id="p42" title="42"/><p>Copper birds gather near the water.</p></body></html>')
        library = Library(root)
        library.sync(semantic=False)
    hit = library.search("copper birds", engine="exact")["direct"][0]
    verified_book(library, hit, format="EPUB" if source.suffix == ".epub" else "Microsoft Word document")
    return library, hit


@pytest.fixture
def client(source_library):
    library, _ = source_library
    with TestClient(create_app(library, enable_intake_worker=False), base_url=ORIGIN) as client:
        yield client


def tree(response):
    """The structured view replaces Jinja DOM; React tests assert rendered controls."""
    assert response.status_code == 200, response.text
    return response.json()['data']


def form_values(document, action):
    """Build the documented JSON form fields from the returned view model.

    Actual browser control serialization is covered by React component tests.
    """
    if action.startswith('/bibliography/'):
        target = document['target']
        record = target['record']
        values = {key: '' if record.get(key) is None else str(record[key]) for key in document['fields']}
        values['passage_id'] = document.get('passage_id', '')
        def name(person):
            if person.get('literal'):
                return person['literal']
            full = ' '.join(str(person.get(key) or '') for key in ('given', 'family')).strip()
            return full + (', ' + person['suffix'] if person.get('suffix') else '')
        for role in document['roles']:
            people = record.get(role) or []
            values[role] = '\n'.join(name(person) for person in people)
            values[role + '_short'] = '\n'.join(person.get('short', '') for person in people)
        if record.get('authors') == []:
            values['authors_absent'] = 'yes'
        if target['is_section']:
            values['type'] = record.get('type') or 'chapter'
            values['scripture_scope'] = record.get('scripture_scope') or ''
            if record.get('translators') is not None:
                values['translators_override'] = 'yes'
        values['evidence'] = ''
        return values
    locator = document.get('locator') or {}
    values = {'segment': document.get('segment_id', ''), 'locator_type': locator.get('type', document.get('locator_type') or 'page'),
              'locator_value': locator.get('value', document.get('locator_value', '')), 'locator_evidence': locator.get('evidence', '')}
    if locator.get('verified'):
        values['locator_verified'] = 'yes'
    if action.endswith('/export'):
        values['format'] = 'txt'
    return values


def post(client, action, values, csrf=True, origin=ORIGIN):
    headers = {'Origin': origin}
    if csrf:
        headers['X-CSRF-Token'] = client.get('/api/ui/bootstrap').json()['csrf']
    return client.post('/api/ui' + action, json={'fields': values}, headers=headers)


def preview(client, hit, locator="42–43", verified=True):
    action = f"/cite/{hit['id']}/preview"
    data = form_values(tree(client.get(f"/api/ui/cite/{hit['id']}")), action)
    data.update(locator_type="page", locator_value=locator,
                locator_evidence="Printed page numbers inspected in this fixture.")
    if verified:
        data["locator_verified"] = "yes"
    return tree(post(client, action, data))


def test_citation_view_has_plain_formatted_and_verified_locator_data(client, source_library):
    # Copy labels, readonly controls and safe rich formatting are checked in React.
    library, hit = source_library
    document = preview(client, hit)
    expected = library.cite(hit['id'], page('42–43'))
    assert not document['citation']['needs_review']
    for key in KEYS:
        assert document['citation'][key] == expected[key]
        assert document['citation']['html'][key] == expected['html'][key]
    assert '<i>' in document['citation']['html']['full_note']
    assert document['locator']['verified'] and document['locator']['value'] == '42–43'


@pytest.mark.parametrize("export_format", ["txt", "md", "json"])
def test_verified_export_matches_preview_and_does_not_persist_locator(client, source_library, export_format):
    library, hit = source_library
    before = library.bibliography_record(hit["section_id"])["record"]
    document = preview(client, hit, "45–46")
    action = f"/cite/{hit['id']}/export"
    values = form_values(document, action)
    values["format"] = export_format
    response = post(client, action, values)
    assert response.status_code == 200
    assert "attachment;" in response.headers["content-disposition"]
    expected = library.cite(hit["id"], {"type": "page", "value": "45–46", "verified": True, "evidence": values["locator_evidence"]})
    if export_format == "json":
        actual = response.json()
        for key in KEYS:
            assert actual[key] == document["citation"][key]
        assert actual["ready"] and actual["locator"]["value"] == "45–46"
        assert actual["citation_id"] == expected["citation_id"]
    else:
        expected_values = expected["markdown"] if export_format == "md" else expected
        for key in KEYS:
            assert expected_values[key] in response.text
    assert library.bibliography_record(hit["section_id"])["record"] == before


def test_unverified_get_locator_cannot_be_silently_promoted(client, source_library):
    _, hit = source_library
    params = {'locator_type': 'page', 'locator_value': '99', 'locator_verified': 'yes'}
    document = tree(client.get(f"/api/ui/cite/{hit['id']}", params=params))
    assert document['citation']['needs_review']
    exported = client.get(f"/api/ui/cite/{hit['id']}/export", params={**params, 'format': 'json'}).json()
    assert exported['locator']['value'] == '99'
    assert not exported['locator']['verified'] and exported['needs_review']
    assert exported['full_note'] == document['citation']['full_note']


def test_source_metadata_stays_data_in_preview_and_editor(client, source_library):
    # React tests enforce escaping without dangerous raw-HTML rendering.
    library, hit = source_library
    hostile = '</textarea><script>alert("source")</script><img src="https://example.org/tracker" onerror="bad()">'
    bib(library, hit['work_id'], {'title': hostile, 'publisher': 'A & B <Press>'})
    for path in (f"/cite/{hit['id']}", f"/bibliography/{hit['work_id']}"):
        response = client.get('/api/ui' + path)
        assert response.status_code == 200
        assert response.headers['content-type'].startswith('application/json')
        assert "script-src 'self'" in response.headers['content-security-policy']
    document = tree(client.get(f"/api/ui/cite/{hit['id']}"))
    assert hostile in document['citation']['full_note']
    assert '<script>' not in document['citation']['html']['full_note']
    assert '&lt;script&gt;' in document['citation']['html']['full_note']
    editor = tree(client.get(f"/api/ui/bibliography/{hit['work_id']}"))
    assert editor['target']['record']['title'] == hostile


@pytest.mark.parametrize("role", ["authors", "editors", "translators"])
def test_editing_publication_preserves_structured_names_with_short_names(client, source_library, role):
    library, hit = source_library
    person = {"given": "Jane", "family": "Doe", "short": "Doe", "suffix": "Jr."}
    bib(library, hit["work_id"], {role: [person]})
    action = f"/bibliography/{hit['work_id']}"
    document = tree(client.get("/api/ui" + action))
    values = form_values(document, action)
    values.update(publisher="Corrected Press", evidence="Checked the edition's publication page.")
    response = post(client, action, values)
    assert response.status_code == 200
    assert library.bibliography_record(hit["work_id"])["record"][role] == [person]
    bib(library, hit["work_id"], {"publisher": "Codex Guess"}, status="provisional", origin="codex")
    assert library.bibliography_record(hit["work_id"])["record"]["publisher"] == "Corrected Press"


def test_editor_exposes_complete_structured_names(client, source_library):
    library, hit = source_library
    person = {'given': 'Jane', 'family': 'Doe', 'suffix': 'Jr.'}
    bib(library, hit['work_id'], {'authors': [person]})
    document = tree(client.get(f"/api/ui/bibliography/{hit['work_id']}"))
    assert document['target']['record']['authors'] == [person]
    assert form_values(document, f"/bibliography/{hit['work_id']}")['authors'] == 'Jane Doe, Jr.'


def test_reordering_authors_and_editing_short_names_keeps_structure(client, source_library):
    library, hit = source_library
    first = {"given": "Jane", "family": "Doe", "suffix": "Jr.", "short": "Doe"}
    second = {"given": "Mira", "family": "Writer"}
    bib(library, hit["work_id"], {"authors": [first, second]})
    action = f"/bibliography/{hit['work_id']}"
    values = form_values(tree(client.get("/api/ui" + action)), action)
    values.update(authors="Mira Writer\nJane Doe, Jr.", authors_short="Writer\nDoe Jr.",
                  evidence="Corrected order and shortened forms from the title page.")
    assert post(client, action, values).status_code == 200
    assert library.bibliography_record(hit["work_id"])["record"]["authors"] == [
        {**second, "short": "Writer"}, {**first, "short": "Doe Jr."}]
    assert library.cite(hit["id"], page())["bibliography"].startswith("Writer, Mira, and Jane Doe, Jr.")


def test_explicitly_cleared_metadata_remains_null_in_editor_data(client, source_library):
    library, hit = source_library
    bib(library, hit['work_id'], {'authors': None, 'publisher': None, 'year': None})
    document = tree(client.get(f"/api/ui/bibliography/{hit['work_id']}"))
    assert all(document['target']['record'][key] is None for key in ['authors', 'publisher', 'year'])
    values = form_values(document, f"/bibliography/{hit['work_id']}")
    assert all(values[key] == '' for key in ['authors', 'publisher', 'year'])


def test_section_editor_inherits_book_metadata_without_promoting_editor_to_author(client, source_library):
    library, hit = source_library
    verified_book(library, hit, authors=[], editors=[{"given": "Avery", "family": "Editor"}])
    action = f"/bibliography/{hit['section_id']}"
    document = tree(client.get("/api/ui" + action, params={"passage": hit["id"]}))
    assert "publisher" not in document["fields"] and "year" not in document["fields"]
    values = form_values(document, action)
    values.update(type="chapter", title="Learning in Community", short_title="Learning",
                  authors="Ruth Writer", authors_short="Writer",
                  evidence="Chapter opening identifies Ruth Writer as contributor.")
    response = post(client, action, values)
    assert response.status_code == 200
    assert response.json()["redirect"] == f"/cite/{hit['id']}?saved=true"
    citation = library.cite(hit["id"], page())
    assert citation["ready"]
    assert citation["full_note"].startswith('Ruth Writer, “Learning in Community,” in ')
    assert "ed. Avery Editor (Example Press, 2024)" in citation["full_note"]
    assert citation["short_note"] == 'Writer, “Learning,” 42.'
    assert citation["bibliography"].startswith('Ruth Writer. “Learning in Community.”')
    record = library.bibliography_record(hit["section_id"])["record"]
    assert "publisher" not in record and "year" not in record


def test_new_section_keeps_volume_translation_credit_unless_replaced(client, source_library):
    library, hit = source_library
    verified_book(library, hit, authors=[], editors=[{"given": "Avery", "family": "Editor"}],
                  translators=[{"given": "Tessa", "family": "Translator"}])
    action = f"/bibliography/{hit['section_id']}"
    values = form_values(tree(client.get("/api/ui" + action)), action)
    values.update(type="poem", title="River Song", authors="Ruth Writer",
                  evidence="Poem byline identifies Ruth Writer; translation credit is on the volume title page.")
    assert post(client, action, values).status_code == 200
    result = library.cite(hit["id"], page())
    assert "trans. Tessa Translator" in result["full_note"]
    assert "Translated by Tessa Translator." in result["bibliography"]


@pytest.mark.parametrize("override", ["Riley Translator", ""])
def test_section_translation_override_can_be_saved_and_returned_to_inheritance(client, source_library, override):
    library, hit = source_library
    verified_book(library, hit, authors=[], editors=[{"given": "Avery", "family": "Editor"}],
                  translators=[{"given": "Tessa", "family": "Translator"}])
    action = f"/bibliography/{hit['section_id']}"
    document = tree(client.get("/api/ui" + action))
    assert document["target"]["record"].get("translators") is None
    assert document["inherited_translators"] == [{"given": "Tessa", "family": "Translator"}]
    values = form_values(document, action)
    values.update(type="poem", title="River Song", authors="Ruth Writer",
                  translators_override="yes", translators=override,
                  evidence="Inspected the poem's own translation attribution.")
    assert post(client, action, values).status_code == 200
    result = library.cite(hit["id"], page())
    assert result["ready"] and "Tessa Translator" not in result["full_note"]
    if override:
        assert "trans. Riley Translator" in result["full_note"]
    else:
        assert "trans." not in result["full_note"]
    saved = tree(client.get("/api/ui" + action))
    assert saved["target"]["record"].get("translators") is not None
    values = form_values(saved, action)
    values.pop("translators_override")
    values["evidence"] = "Rechecked: the volume's translation credit applies here."
    assert post(client, action, values).status_code == 200
    assert library.bibliography_record(hit["section_id"])["record"]["translators"] is None
    assert "trans. Tessa Translator" in library.cite(hit["id"], page())["full_note"]
    assert library.bibliography_record(hit["work_id"])["record"]["translators"] == [{"given": "Tessa", "family": "Translator"}]


@pytest.mark.parametrize("contribution", [False, True])
def test_blank_author_requires_explicit_verification_before_anonymity(client, source_library, contribution):
    library, hit = source_library
    target = hit["section_id"] if contribution else hit["work_id"]
    action = f"/bibliography/{target}"
    document = tree(client.get("/api/ui" + action))
    values = form_values(document, action)
    values.update(authors="", authors_short="", evidence="The current attribution is incorrect; no replacement has been verified.")
    if contribution:
        values.update(type="poem", title="River Song")
    assert post(client, action, values).status_code == 200
    assert library.bibliography_record(target)["record"].get("authors") is None
    unknown = library.cite(hit["id"], page())
    assert unknown["needs_review"] and "authors" in unknown["missing_fields"]
    values = form_values(tree(client.get("/api/ui" + action)), action)
    values.update(authors_absent="yes", evidence="The source explicitly identifies this contribution as anonymous.")
    assert post(client, action, values).status_code == 200
    assert library.bibliography_record(target)["record"]["authors"] == []
    assert library.cite(hit["id"], page())["ready"]
    # Conflicting inputs cannot silently discard a named author.
    values.update(authors="Ruth Writer")
    assert post(client, action, values).status_code == 400
    assert library.bibliography_record(target)["record"]["authors"] == []


def test_cleared_author_is_unknown_rather_than_verified_anonymous(client, source_library):
    library, hit = source_library
    bib(library, hit["work_id"], {"authors": None})
    exported = preview(client, hit)
    assert exported["citation"]["needs_review"]
    values = form_values(exported, f"/cite/{hit['id']}/export")
    values["format"] = "json"
    result = post(client, f"/cite/{hit['id']}/export", values).json()
    assert not result["ready"]
    assert "authors" in result["missing_fields"] or "authors" in result["review_fields"]


def test_invalid_source_url_rejects_edit_without_partial_curation(client, source_library):
    library, hit = source_library
    action = f"/bibliography/{hit['work_id']}"
    values = form_values(tree(client.get("/api/ui" + action)), action)
    before = library.bibliography_record(hit["work_id"])["record"]
    values.update(publisher="Attempted change", url="javascript:alert(1)", evidence="Invalid URL fixture.")
    assert post(client, action, values).status_code == 400
    assert library.bibliography_record(hit["work_id"])["record"] == before


@pytest.mark.parametrize("endpoint", ["bibliography", "preview", "export"])
def test_citation_posts_require_same_origin_and_csrf(client, source_library, endpoint):
    library, hit = source_library
    if endpoint == 'bibliography':
        action = f"/bibliography/{hit['work_id']}"
        values = form_values(tree(client.get('/api/ui' + action)), action)
        values.update(title='Unauthorized replacement', evidence='Attempted change.')
    else:
        action = f"/cite/{hit['id']}/{endpoint}"
        values = form_values(tree(client.get(f"/api/ui/cite/{hit['id']}")), action)
    before = library.bibliography_record(hit['work_id'])['record']
    assert post(client, action, values, origin='https://example.org').status_code == 403
    assert post(client, action, values, csrf=False).status_code == 403
    assert library.bibliography_record(hit['work_id'])['record'] == before


def test_locator_verification_requires_evidence_and_rejects_block_page(client, source_library):
    _, hit = source_library
    action = f"/cite/{hit['id']}/preview"
    values = form_values(tree(client.get(f"/api/ui/cite/{hit['id']}")), action)
    values.update(locator_type="page", locator_value="42", locator_verified="yes", locator_evidence="")
    assert post(client, action, values).status_code == 400
    values.update(locator_value="block 42", locator_evidence="An extraction ordinal, not a printed page.")
    assert post(client, action, values).status_code == 400


def test_cli_json_matches_api_and_emits_review_when_docx_has_no_source_pages(client, source_library):
    library, hit = source_library
    command = [sys.executable, "-m", "book_library.cli", "--root", str(library.root), "cite", hit["id"]]
    run = subprocess.run([*command, "--json"], capture_output=True, text=True, timeout=20)
    assert run.returncode == 0, run.stderr
    result = json.loads(run.stdout)
    assert result == client.get(f"/api/cite/{hit['id']}").json()
    assert result["source_identity"]["work_id"] == hit["work_id"]
    assert result["source_identity"]["section_id"] == hit["section_id"]
    assert len(run.stdout) < 20000
    human = subprocess.run([*command, "--format", "short"], capture_output=True, text=True, timeout=20)
    assert human.returncode == 0 and human.stdout.strip() == result["short_note"]
    if hit["source_paths"][0].endswith(".docx"):
        assert result["needs_review"] and "locator" in result["review_fields"]
        assert "Review:" in human.stderr
        assert "block " not in result["full_note"]
    else:
        assert result["ready"] and result["locator"]["value"] == "42"
    invalid = subprocess.run([*command, "--locator", '{"type":"page","value":"42","verified":true}', "--json"], capture_output=True, text=True, timeout=20)
    assert invalid.returncode == 1
    assert "evidence" in json.loads(invalid.stderr)["error"]


@pytest.fixture
def provisional_year(tmp_path):
    root = tmp_path / "books"
    source = docx(root / "Classroom.docx", [("Heading1", "Learning in Community"),
                                            "Copper birds gather near the water."])
    library = seed(root, [{"title": TITLE, "author": "Jane Doe", "paths": [source]}])
    hit = library.search("copper birds", engine="exact")["direct"][0]
    bib(library, hit["work_id"], {"title": TITLE, "authors": [{"given": "Jane", "family": "Doe"}],
                                 "publisher": "Example Press"})
    # Integer-to-text conversion in a submitted field must not count as an edit.
    bib(library, hit["work_id"], {"year": 2024}, status="provisional", origin="codex")
    with TestClient(create_app(library, enable_intake_worker=False), base_url=ORIGIN) as client:
        yield library, hit, client


@pytest.mark.parametrize("verify_unchanged", [False, True])
def test_publisher_edit_verifies_candidate_year_only_with_explicit_checkbox(provisional_year, verify_unchanged):
    library, hit, client = provisional_year
    previous = library.cite(hit["id"], page())
    assert previous["provenance"]["year"]["status"] == "provisional"
    assert previous["provenance"]["year"]["origin"] == "codex"
    action = f"/bibliography/{hit['work_id']}"
    document = tree(client.get("/api/ui" + action))
    values = form_values(document, action)
    values.update(publisher="Corrected Press", evidence="Verified the publication details printed in this edition.")
    if verify_unchanged:
        values["verify_unchanged"] = "yes"
    assert post(client, action, values).status_code == 200
    result = library.cite(hit["id"], page())
    assert result["metadata"]["publisher"] == "Corrected Press"
    assert result["provenance"]["publisher"]["origin"] == "user"
    assert result["provenance"]["publisher"]["status"] == "confirmed"
    if verify_unchanged:
        assert result["provenance"]["year"]["origin"] == "user"
        assert result["provenance"]["year"]["status"] == "confirmed"
        assert result["ready"]
    else:
        assert result["provenance"]["year"] == previous["provenance"]["year"]
        assert "year" in result["review_fields"] and result["needs_review"]
        assert library._curation()[-1]["value"] == {"publisher": "Corrected Press"}


def test_noop_editor_save_keeps_annotation_history_and_candidate_provenance(provisional_year):
    library, hit, client = provisional_year
    before = library._curation()
    action = f"/bibliography/{hit['work_id']}"
    values = form_values(tree(client.get("/api/ui" + action)), action)
    values["evidence"] = "No correction was needed; unrelated fields were not checked."
    response = post(client, action, values)
    assert response.status_code == 200 and "unchanged=true" in response.json()["redirect"]
    assert tree(client.get("/api/ui" + response.json()["redirect"]))["unchanged"]
    assert library._curation() == before
    assert library.cite(hit["id"], page())["provenance"]["year"]["status"] == "provisional"


def test_verify_unchanged_does_not_promote_unknown_blank_author(provisional_year):
    library, hit, client = provisional_year
    bib(library, hit["work_id"], {"authors": None})
    action = f"/bibliography/{hit['work_id']}"
    values = form_values(tree(client.get("/api/ui" + action)), action)
    assert "authors_absent" not in values
    values.update(verify_unchanged="yes", evidence="Verified the displayed publication details; author remains unknown.")
    assert post(client, action, values).status_code == 200
    assert library.bibliography_record(hit["work_id"])["record"]["authors"] is None
    assert "authors" not in library._curation()[-1]["value"]
    assert "edition" not in library._curation()[-1]["value"]
    result = library.cite(hit["id"], page())
    assert result["needs_review"] and "authors" in result["missing_fields"]


def test_verifying_section_fields_does_not_promote_inherited_book_details(provisional_year):
    library, hit, client = provisional_year
    bib(library, hit["section_id"], {"title": "Learning in Community", "type": "chapter",
                                    "authors": [{"given": "Ruth", "family": "Writer"}]},
        status="provisional", origin="codex")
    before = library.cite(hit["id"], page())
    action = f"/bibliography/{hit['section_id']}"
    values = form_values(tree(client.get("/api/ui" + action)), action)
    values.update(verify_unchanged="yes", evidence="Verified the chapter heading and contribution byline.")
    assert post(client, action, values).status_code == 200
    after = library.cite(hit["id"], page())
    assert after["provenance"]["section.authors"]["status"] == "confirmed"
    assert after["provenance"]["section.title"]["status"] == "confirmed"
    assert after["provenance"]["year"] == before["provenance"]["year"]
    assert "year" in after["review_fields"]
