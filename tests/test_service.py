"""Research-level invariants: source identity, recoverability, and honest retrieval."""
from __future__ import annotations

import json
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZipFile

import pytest

from book_library.service import Library

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def docx(path: Path, paragraphs: list[str | tuple[str, str]]) -> Path:
    """Create a small real package, with headings and explicit Word line breaks."""
    path.parent.mkdir(parents=True, exist_ok=True)
    elements = []
    for item in paragraphs:
        style, text = item if isinstance(item, tuple) else ("", item)
        properties = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
        runs = '<w:br/>'.join(f'<w:t xml:space="preserve">{escape(line)}</w:t>' for line in text.split('\n'))
        elements.append(f'<w:p>{properties}<w:r>{runs}</w:r></w:p>')
    with ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr("word/document.xml", f'<w:document xmlns:w="{W}"><w:body>{"".join(elements)}</w:body></w:document>')
        z.writestr("word/styles.xml", f'<w:styles xmlns:w="{W}"><w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:pPr><w:outlineLvl w:val="0"/></w:pPr></w:style></w:styles>')
    return path


def seed(root: Path, books: list[dict]) -> Library:
    root.mkdir(parents=True, exist_ok=True)
    (root / ".catalog").mkdir(exist_ok=True)
    records = []
    for spec in books:
        paths = spec["paths"]
        records.append({"title": spec["title"], "author": spec.get("author", "Test Author"),
                        "folder": str(paths[0].parent), "bookshare_id": spec.get("bookshare_id"),
                        "files": [{"path": str(p), "name": p.name, "format": "docx"} for p in paths],
                        **spec.get("metadata", {})})
    (root / ".catalog" / "library.json").write_text(json.dumps({"books": records}))
    library = Library(root)
    library.sync()
    return library


def annotate(library, work_id, value, origin="user", field="profile"):
    return library.annotate(work_id, {"field": field, "value": value, "origin": origin,
                                    "status": "confirmed" if origin == "user" else "provisional",
                                    "evidence": "Synthetic fixture's inspected contents and attribution."})


def test_split_word_section_keeps_continuation_and_reading_order(tmp_path):
    root = tmp_path / "books"
    first = docx(root / "A - Commentary" / "001.docx", [("Heading1", "John 9:13–17"), "Neighbors gathered around the witness."])
    second = docx(first.parent / "002.docx", ["The healing became a contested sign.", ("Heading1", "John 9:18–23"), "The next scene follows."])
    lib = seed(root, [{"title": "Commentary", "paths": [first, second]}])
    result = lib.search('"contested sign"')
    assert result["direct"]
    hit = result["direct"][0]
    assert hit["heading"] == "John 9:13–17"
    read = lib.read(hit["id"], context=0)
    joined = '\n'.join(b["text"] for b in read["blocks"])
    assert joined.index("Neighbors gathered") < joined.index("healing became")
    assert set(hit["source_paths"]) == {str(first), str(second)}
    assert "next scene" not in joined


def test_rename_edit_remove_rebuild_preserve_identity_and_corrections(tmp_path):
    root = tmp_path / "books"
    original = docx(root / "A - Research" / "Original.docx", [("Heading1", "Memory"), "Amber sentinel passage."])
    lib = seed(root, [{"title": "Research", "paths": [original]}])
    work_id = lib.books()[0]["id"]
    original_hit = lib.search("amber sentinel")["direct"][0]
    annotate(lib, work_id, "Corrected title", field="title")
    annotate(lib, work_id, {"subjects": ["education"], "themes": ["memory"]})
    lib.sync()
    renamed = original.with_name("Research - Memory.docx")
    original.rename(renamed)
    assert lib.search("amber sentinel")["direct"] == []  # stale path never presented as live
    lib.sync()
    assert lib.books()[0]["id"] == work_id
    assert lib.books()[0]["title"] == "Corrected title"
    hit = lib.search("amber sentinel")["direct"][0]
    assert hit["id"] == original_hit["id"]
    assert hit["source_paths"] == [str(renamed)]
    file_record = lib.book(work_id)["files"][0]
    assert str(original) in file_record["previous_paths"]
    docx(renamed, [("Heading1", "Memory"), "Violet replacement passage with added context."])
    assert lib.search("amber sentinel")["direct"] == []
    lib.sync()
    assert lib.search("violet replacement")["direct"]
    assert not lib.search("amber sentinel")["direct"]
    assert len(lib.book(work_id)["files"][0]["versions"]) == 2
    lib.sync(rebuild=True)
    assert lib.book(work_id)["title"] == "Corrected title"
    assert lib.book(work_id)["profile"]["subjects"] == ["education"]
    renamed.unlink()
    assert not lib.search("violet replacement")["direct"]
    lib.sync()
    assert lib.status()["missing_files"] == [str(renamed)]
    assert lib._catalog()["works"][work_id]["id"] == work_id
    assert lib.book(work_id)["profile"]["themes"] == ["memory"]


def test_curation_merges_fields_without_regenerating_over_user_edits(tmp_path):
    root = tmp_path / "books"
    source = docx(root / "A" / "Book.docx", ["Teaching and remembering in community."])
    lib = seed(root, [{"title": "A", "paths": [source]}])
    work_id = lib.books()[0]["id"]
    annotate(lib, work_id, {"subjects": ["education"], "forms": ["essay"]}, origin="codex")
    annotate(lib, work_id, {"subjects": ["psychology"]})
    annotate(lib, work_id, {"subjects": ["theology"], "themes": ["memory"]}, origin="codex")
    lib.sync(rebuild=True)
    profile = lib.book(work_id)["profile"]
    assert profile["subjects"] == ["psychology"]
    assert profile["forms"] == ["essay"]
    assert profile["themes"] == ["memory"]


def test_direct_connections_filters_unknown_metadata_and_holdings_gap(tmp_path):
    root = tmp_path / "books"
    ecology = docx(root / "Ecology" / "Ecology.docx", ["Ecology traces living relationships within the forest."])
    poem = docx(root / "Poetry" / "Poetry.docx", ["Poetry remembers a river\nthrough the cadence of rain."])
    formation = docx(root / "Formation" / "Formation.docx", ["Spiritual formation grows through reflection and shared teaching."])
    lib = seed(root, [{"title": "Ecology", "paths": [ecology]}, {"title": "Poetry", "paths": [poem]}, {"title": "Formation", "paths": [formation]}])
    for preset in ("sunday-core", "enneagram-workshop"):
        lib.save_focus(preset, json.loads((Path(__file__).resolve().parents[1] / "examples" / "focuses" / (preset + ".json")).read_text()))
    result = lib.search("ecology", focus="sunday-core")
    assert [h["title"] for h in result["direct"]] == ["Ecology"]
    assert any(h["title"] == "Poetry" for h in result["connections"])
    assert all(h["reason"] for h in result["connections"])
    assert not lib.search("ecology", filters={"subject": "ecology"})["direct"]  # explicit filter excludes unknown
    work_id = next(b["id"] for b in lib.books() if b["title"] == "Ecology")
    annotate(lib, work_id, {"subjects": ["ecology"]}, origin="codex")
    lib.sync()
    assert lib.search("ecology", filters={"subject": "ecology"})["direct"]
    from book_library.taxonomy import save_term
    save_term(lib, 'spiritual-formation', {'label': 'Spiritual formation', 'evidence': 'Synthetic discovery vocabulary'})
    save_term(lib, 'enneagram', {'label': 'Enneagram', 'related': ['spiritual-formation'], 'evidence': 'Synthetic discovery vocabulary'})
    gap = lib.search("Enneagram", focus="enneagram-workshop", mode="exploratory")
    assert not gap["direct"]
    assert "No dedicated Enneagram book" in gap["holdings_gap"]
    assert gap["connections"]
    assert all("not evidence" in h["reason"] or "not direct" in h["reason"] for h in gap["connections"])


def test_catalog_mislabel_does_not_become_primary_commentary_coverage(tmp_path):
    root = tmp_path / "books"
    path = docx(root / "Luke2" / "Luke.docx", [("Heading1", "Luke 12"), "Luke 1 is mentioned here incidentally, while Luke 12 supplies this essay's text."])
    lib = seed(root, [{"title": "Feasting on the Gospels: Luke, Volume 2, Chapters 12–24", "paths": [path], "metadata": {"catalog_title": "Luke Volume 1", "catalog_discrepancy": "Publisher contents establish chapters 12–24."}}])
    result = lib.search("Luke 1")
    assert not result["direct"]
    assert result["connections"]
    assert any("incidental" in limit for h in result["connections"] for limit in h["limitations"])
    assert not lib.search("Luke", filters={"scripture": "Luke 1"})["direct"]
    assert lib.search("Luke 12")["direct"]


def test_poem_lineation_and_section_author_survive_rebuild(tmp_path):
    root = tmp_path / "books"
    source = docx(root / "Anthology" / "Poems.docx", [("Heading1", "Rain"), "First bright line\nSecond quiet line\nThird returning line"])
    lib = seed(root, [{"title": "Collected Poetry Anthology", "author": "Volume Editor", "paths": [source]}])
    hit = lib.search("bright line")["direct"][0]
    assert "Contributor unverified" in hit["attribution"]
    annotate(lib, hit["section_id"], "Actual Poet", field="attribution")
    lib.sync(rebuild=True)
    hit = lib.search("bright line")["direct"][0]
    assert hit["attribution"] == "Actual Poet"
    read = lib.read(hit["id"], context=0)
    assert any("First bright line\nSecond quiet line\nThird returning line" in b["text"] for b in read["blocks"])


def test_failed_book_isolated_and_resume_uses_existing_download(tmp_path):
    root = tmp_path / "books"
    good = docx(root / "Healthy" / "Healthy.docx", ["Healthy copper witness."])
    broken = root / "Broken" / "Broken.docx"
    broken.parent.mkdir(parents=True)
    broken.write_bytes(b"not a Word zip")
    lib = seed(root, [{"title": "Healthy", "paths": [good]}, {"title": "Broken", "paths": [broken]}])
    assert lib.search("copper witness")["direct"]
    assert len(lib.status()["failures"]) == 1
    work_id = next(b["id"] for b in lib.books() if b["title"] == "Broken")
    docx(broken, ["Recovered sapphire witness."])
    lib.sync(path=broken)
    assert not lib.status()["failures"]
    assert lib.search("sapphire witness")["direct"][0]["work_id"] == work_id
    assert len(lib._catalog()["works"]) == 2


def test_interrupted_publication_keeps_prior_generation_and_resumes(tmp_path, monkeypatch):
    root = tmp_path / "books"
    first = docx(root / "Known" / "Known.docx", ["Known bronze witness."])
    lib = seed(root, [{"title": "Known", "paths": [first]}])
    generation = lib.status()["generation"]
    added = docx(root / "Added" / "Added.docx", ["Added silver witness."])
    original_index_work = lib._index_work
    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt("simulated interruption before atomic publication")
    monkeypatch.setattr(lib, "_index_work", interrupt)
    with pytest.raises(KeyboardInterrupt):
        lib.sync()
    assert lib.status()["generation"] == generation
    assert lib.search("bronze witness")["direct"]
    monkeypatch.setattr(lib, "_index_work", original_index_work)
    lib.sync()
    assert lib.search("silver witness")["direct"]
    assert len(lib._catalog()["works"]) == 2


def test_inventory_failure_does_not_mark_healthy_sources_missing(tmp_path, monkeypatch):
    root = tmp_path / "books"
    source = docx(root / "Known" / "Known.docx", ["Known platinum witness."])
    lib = seed(root, [{"title": "Known", "paths": [source]}])
    before = lib._catalog()
    def failure():
        raise PermissionError("simulated inventory failure")
    monkeypatch.setattr(lib, "_inventory", failure)
    with pytest.raises(PermissionError):
        lib.sync()
    assert lib._catalog() == before
    assert lib.search("platinum witness")["direct"]


def test_search_and_read_do_not_open_original_books(tmp_path, monkeypatch):
    root = tmp_path / "books"
    source = docx(root / "Known" / "Known.docx", ["Indexed emerald witness."])
    lib = seed(root, [{"title": "Known", "paths": [source]}])
    original_open = Path.open
    def guarded_open(path, *args, **kwargs):
        if path.suffix.lower() in (".docx", ".epub"):
            raise AssertionError("Research must use the index, not reopen original book content")
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", guarded_open)
    hit = lib.search("emerald witness")["direct"][0]
    assert "emerald" in lib.read(hit["id"])["passage"]["text"]
    assert lib.status()["freshness"]["fresh"]
    assert not lib.sync()["changed"]


def test_open_reader_survives_new_generations(tmp_path):
    root = tmp_path / "books"
    source = docx(root / "Known" / "Known.docx", ["Persistent quartz witness."])
    lib = seed(root, [{"title": "Known", "paths": [source]}])
    with lib._db() as old_reader:
        assert old_reader.execute("SELECT count(*) FROM passages").fetchone()[0] > 0
        for _ in range(3):
            lib.sync(rebuild=True)
        assert old_reader.execute("SELECT text FROM passages").fetchone()[0].endswith("quartz witness.")
    assert lib.search("quartz witness")["direct"]


def test_section_facets_filter_passages_without_excluding_unclassified_work(tmp_path):
    root = tmp_path / "books"
    source = docx(root / "Collection" / "Collection.docx", [("Heading1", "Verse"), "Water remembers the shore.", ("Heading1", "Analysis"), "Water carries sediment downstream."])
    lib = seed(root, [{"title": "Collection", "paths": [source]}])
    wid = lib.books()[0]["id"]
    sections = lib.book(wid)["sections"]
    sid = next(s["id"] for s in sections if s["title"] == "Verse")
    annotate(lib, sid, {"forms": ["poem"], "subjects": ["ecology"]})
    lib.sync()
    result = lib.search("water", filters={"form": "poem"})
    assert [h["heading"] for h in result["direct"]] == ["Verse"]
    assert lib.search("water", filters={"subject": "ecology"})["direct"][0]["section_id"] == sid


def test_context_does_not_reveal_stale_adjacent_file(tmp_path):
    root = tmp_path / "books"
    first = docx(root / "Study" / "001.docx", [("Heading1", "Beginning"), "Stable amber passage."])
    second = docx(first.parent / "002.docx", [("Heading1", "Continuation"), "Old violet context must not leak."])
    lib = seed(root, [{"title": "Study", "paths": [first, second]}])
    first_hit = lib.search("stable amber")["direct"][0]
    docx(second, [("Heading1", "Continuation"), "Revised indigo context."])
    try:
        reading = lib.read(first_hit["id"], context=2)
    except ValueError as exc:
        assert "sync" in str(exc).lower() or "changed" in str(exc).lower()
    else:
        assert "Old violet" not in '\n'.join(b["text"] for b in reading["blocks"])
        assert reading.get("warnings") or reading.get("limitations")


def test_new_acquisition_manifest_indexes_without_legacy_audit(tmp_path):
    root = tmp_path / "books"
    root.mkdir()
    lib = Library(root)
    lib.sync()
    source = docx(root / "Author - New Book" / "New Book.docx", ["Newly acquired sapphire text."])
    (root / ".catalog").mkdir()
    (root / ".catalog" / "bookshare-123456.json").write_text(json.dumps({
        "books": [{"bookshare_id": "123456", "title": "Verified New Book", "author": "Verified Author", "folder": str(source.parent), "source_url": "https://www.bookshare.org/browse/book/123456"}],
        "files": [{"bookshare_id": "123456", "path": str(source), "format": "docx", "sequence": 1}],
    }))
    lib.sync(path=source.parent)
    hit = lib.search("acquired sapphire")["direct"][0]
    assert hit["title"] == "Verified New Book"
    assert hit["attribution"] == "Verified Author"
    acquisitions = list(lib._catalog()["acquisitions"].values())
    assert len(acquisitions) == 1
    assert acquisitions[0]["provider_id"] == "123456"
    assert acquisitions[0]["stage"] == "text_ready"
    lib.sync(path=source.parent)
    assert len(lib._catalog()["acquisitions"]) == 1


def test_focus_default_breadth_is_applied_unless_explicitly_overridden(tmp_path):
    root = tmp_path / "books"
    source = docx(root / "Study" / "Study.docx", [("Heading1", "River One"), "Water comes quietly.", ("Heading1", "River Two"), "Water returns gently."])
    lib = seed(root, [{"title": "Study", "paths": [source]}])
    default = lib.search("water", focus="explore-connections")
    assert default["mode"] == "exploratory"
    assert len(default["direct"]) == 1
    explicit = lib.search("water", focus="explore-connections", mode="balanced")
    assert explicit["mode"] == "balanced"
    assert len(explicit["direct"]) == 2
