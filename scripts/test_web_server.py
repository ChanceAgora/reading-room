"""Disposable browser-test library. No real books, worker, or paid providers."""
from __future__ import annotations

import atexit
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]

from book_library.service import Library
from book_library.web import create_app
from book_library import review_ai
from test_service import docx

directory = TemporaryDirectory(prefix="reading-room-browser-")
atexit.register(directory.cleanup)
root = Path(directory.name)
source = docx(root / "The River" / "Source.docx", [
    ("Heading1", "Publication"), "The River and the Thread", "Jane Doe", "Example Press, 2024",
    ("Heading1", "A gathering"), "Copper birds gather beside the river. A thread connects their stories.",
    "A second line of poetry\ncontinues quietly.",
    '<script>window.sourceWasExecuted = true</script>',
    ("Heading1", "Another chapter"), "Silver bells mark the morning.",
])
(root / ".catalog").mkdir()
(root / ".catalog" / "library.json").write_text(json.dumps({"books": [{"title": "The River and the Thread", "author": "Jane Doe", "folder": str(source.parent), "files": [{"path": str(source), "name": source.name, "format": "docx"}]}]}))
library = Library(root)
library.sync(semantic=False)
library._local_base_url = "http://127.0.0.1:18767"
searches: list[dict] = []
original_search = library.search
original_sync = library.sync


def search(query, **kwargs):
    searches.append({"query": query, "requested_engine": kwargs.get("engine", "combined")})
    return original_search(query, **{**kwargs, "engine": "exact"})


def disabled_ai(*args, **kwargs):
    raise ValueError("Paid providers are disabled in the browser fixture.")


library.search = search
library.sync = lambda *args, **kwargs: original_sync(*args, **{**kwargs, "semantic": False})
review_ai.suggest = disabled_ai
app = create_app(library, enable_intake_worker=False)


@app.get("/__testing/state")
def observations():
    work = library.books()[0]
    hit = original_search("copper birds", engine="exact")["direct"][0]
    return {"searches": searches, "work_id": work["id"], "hit": hit, "curation_count": len(library._curation())}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=18767)
