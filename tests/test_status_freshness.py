"""Source freshness and derived-index freshness are independent facts."""

from book_library.storage import atomic_json
from test_service import docx, seed


def test_durable_work_metadata_change_marks_index_pending_until_sync(tmp_path):
    root = tmp_path / "books"
    source = docx(root / "Art" / "Art.docx", ["An amber drawing on paper."])
    lib = seed(root, [{"title": "Art", "paths": [source]}])
    before = lib.status()
    assert before["index_pending"] is False
    assert before["freshness"]["fresh"] is True

    catalog = lib._catalog()
    work = next(iter(catalog["works"].values()))
    work["metadata"]["source_quality_note"] = "The caption needs attribution verification."
    atomic_json(lib.state / "catalog.json", catalog)
    pending = lib.status()
    assert pending["index_pending"] is True
    assert pending["freshness"]["fresh"] is True

    lib.sync()
    after = lib.status()
    assert after["index_pending"] is False
    assert after["freshness"]["fresh"] is True
    assert after["generation"] != before["generation"]
    hit = lib.search("amber drawing")["direct"][0]
    assert "The caption needs attribution verification." in hit["limitations"]
