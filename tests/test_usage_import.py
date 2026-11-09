"""Usage import respects explicit editorial states rather than inferring actual use."""
import json
from pathlib import Path

from book_library.usage_import import import_usage
from test_service import docx, seed


def save(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def test_import_conservative_states_uncertainty_renames_and_idempotency(tmp_path):
    root = tmp_path / "books"
    source = docx(root / "Known" / "Known.docx", ["A remembered stream."])
    lib = seed(root, [{"title": "Water and Memory", "paths": [source]}])
    work_id = lib.books()[0]["id"]
    old_path = str(source)
    source.rename(source.with_name("Water and Memory.docx"))
    lib.sync()
    lessons = tmp_path / "lessons"
    lesson = lessons / "2026-11-01-proper"
    save(lesson / "art-manifest.json", {
        "quotations": [
            {"id": "q1", "local_source_path": old_path, "work": "Water and Memory", "exact_text": "A remembered stream."},
            {"id": "q2", "work": "Water and Memory", "exact_text": "A proposed unverified quotation."},
        ],
        "recommended_quotation_ids": ["q1"],
        "assets": [],
    })
    save(lesson / "status.json", {"state": "complete", "approved_quotation_ids": ["q1"], "approved_art_ids": []})
    ledger = lesson / "_work/daily-inspiration/discovery-ledger.json"
    save(ledger, {"installments": [{"date": "2026-10-30", "work": "Unresolved Work", "completed": True}]})
    save(ledger.with_name("discovery-ledger-before.json"), {"installments": [{"work": "Ignored backup"}]})
    first = import_usage(lib, lessons)
    events = lib.usage(limit=100)
    assert first["imported"] == 5
    assert not any(e["kind"] == "used" for e in events)
    q1 = [e for e in events if e["source_record"].get("id") == "q1"]
    assert {e["kind"] for e in q1} == {"offered", "recommended", "selected"}
    assert all(e["work_id"] == work_id and e["match_status"] == "verified_path" for e in q1)
    q2 = next(e for e in events if e["source_record"].get("id") == "q2")
    assert q2["kind"] == "offered"
    assert q2["work_id"] is None
    assert q2["candidate_work_ids"] == [work_id]
    assert q2["match_status"] == "unresolved"
    assert all("before" not in e["evidence"] for e in events)
    assert import_usage(lib, lessons)["imported"] == 0
    assert len(lib.usage(limit=100)) == 5
