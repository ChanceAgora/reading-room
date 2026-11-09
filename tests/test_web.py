from __future__ import annotations

from copy import deepcopy
import json
import re
from urllib.parse import urlencode

from fastapi.testclient import TestClient
from lxml import html
import pytest

from book_library.web import create_app

ORIGIN = "http://127.0.0.1:8765"


class FakeLibrary:
    def __init__(self):
        self.calls = []
        self.focus_items = [{"id": "sunday-core", "name": "Sunday Thread", "description": "Explore Scripture and art", "subjects": ["theology"], "forms": [], "books": [], "breadth": "balanced", "related_subjects": ["poetry"]}]
        self.work = {"id": "work-1", "title": "Bodies & ritual", "author": "A. Reader", "files": [{"path": "/books/Bodies.docx", "available": True}], "profile": {"subjects": ["theology"], "forms": ["essay"]}, "sections": [{"id": "section-1", "title": "The public body", "passage_id": "passage-1", "count": 3}]}
        self.hit = {"id": "passage-1", "work_id": "work-1", "title": self.work["title"], "attribution": "Chapter by B. Writer", "location": "Chapter 2 · block 18", "text": "The body appears in public ritual.", "reason": "Text and heading overlap", "limitations": ["Page numbers unavailable"], "source_paths": ["/books/Bodies.docx"]}

    def status(self):
        self.calls.append(("status", {}))
        return {"books": 1, "ready_files": 1, "sections": 1, "passages": 3, "freshness": {"fresh": True}, "semantic": {"state": "awaiting_pilot_review", "coverage_books": 0}}

    def sync(self):
        self.calls.append(("sync", {}))
        return {"changed": False}

    def search(self, query, **kwargs):
        self.calls.append(("search", {"query": query, **kwargs}))
        return {"direct": [deepcopy(self.hit)], "connections": [], "coverage": {"exact_books": 1, "semantic_books": 0}, "warnings": ["Semantic coverage is incomplete."], "holdings_gap": None}

    def read(self, passage_id, context=3):
        self.calls.append(("read", {"id": passage_id, "context": context}))
        if passage_id == "missing":
            raise KeyError(passage_id)
        return {"passage": deepcopy(self.hit), "blocks": [{"id": "block-1", "kind": "paragraph", "text": "First selected paragraph.", "location": "Block 18", "attribution": self.hit["attribution"], "selected": True}, {"id": "block-2", "kind": "paragraph", "text": "Second selected paragraph.", "location": "Block 19", "attribution": self.hit["attribution"], "selected": True}], "work": deepcopy(self.work), "section": {"id": "section-1", "title": "The public body", "profile": {"forms": ["essay"]}}, "previous": None, "next": "passage-2"}

    def books(self, query="", facet=None, limit=50, offset=0):
        self.calls.append(("books", {"query": query, "facet": facet, "limit": limit, "offset": offset}))
        return [deepcopy(self.work)] if not offset else []

    def browse_books(self, query="", facet=None, sort="title", limit=50, offset=0):
        if sort not in ("title", "creator"):
            raise ValueError("Choose title or creator order.")
        total = len(self.books(query=query, facet=facet, limit=100000, offset=0))
        items = self.books(query=query, facet=facet, limit=limit, offset=offset)
        return {"books": items, "total": total, "offset": offset, "limit": limit,
                "sort": sort, "has_more": offset + len(items) < total}

    def book(self, work_id, section_offset=0, section_limit=100):
        if work_id != "work-1":
            raise KeyError(work_id)
        work = deepcopy(self.work)
        sections = work["sections"]
        work["sections"] = sections[section_offset:section_offset+section_limit]
        work["sections_total"] = len(sections)
        work["next_section_offset"] = section_offset+section_limit if section_offset+section_limit < len(sections) else None
        work["previous_section_offset"] = max(0, section_offset-section_limit) if section_offset else None
        return work

    def focuses(self):
        return deepcopy(self.focus_items)

    def save_focus(self, focus_id, data):
        self.calls.append(("save_focus", {"id": focus_id, **data}))
        self.focus_items = [x for x in self.focus_items if x["id"] != focus_id] + [{"id": focus_id, **data}]
        return data

    def annotate(self, target_id, data):
        self.calls.append(("annotate", {"target_id": target_id, **data}))
        return {"index_refresh_required": True}

    def usage(self, limit=50):
        return [{"title": self.hit["title"], "passage_id": self.hit["id"], "purpose": "research", "kind": "inspected", "notes": "Useful for a future class"}]

    def record_usage(self, data):
        self.calls.append(("record_usage", data))
        return data


@pytest.fixture
def library():
    return FakeLibrary()


@pytest.fixture
def client(library):
    with TestClient(create_app(library), base_url=ORIGIN) as client:
        yield client


def token(client, path="/status"):
    return client.get('/api/ui/bootstrap').json()['csrf']


def submit(client, path, values, page="/status", **kwargs):
    data = {"csrf": token(client, page), **values}
    return client.post(path, data=data, headers={"Origin": ORIGIN}, follow_redirects=False, **kwargs)


def ui(client, path):
    response = client.get('/api/ui' + path)
    assert response.status_code == 200, response.text
    return response.json()['data']


@pytest.mark.parametrize("path", ["/", "/search?q=ritual", "/books", "/books/work-1", "/read/passage-1", "/focus", "/focus/new", "/focus/sunday-core", "/focus/sunday-core/books", "/metadata/work-1?work=work-1", "/metadata/section-1?work=work-1", "/history", "/status"])
def test_pages_have_typed_read_only_view_models(client, library, path):
    response = client.get('/api/ui' + path)
    assert response.status_code == 200, response.text
    assert response.json()['page']
    assert response.json()['title']
    assert isinstance(response.json()['data'], dict)
    assert "frame-ancestors 'none'" in response.headers['content-security-policy']
    assert response.headers['cache-control'] == 'no-store'
    assert not any(name in {'sync', 'annotate', 'save_focus', 'record_usage'} for name, _ in library.calls)


def test_untrusted_book_text_and_query_stay_data(client, library):
    malicious = '<script src="https://bad.example/x.js">steal()</script>'
    library.hit.update(title=malicious, text=malicious, reason=malicious)
    data = submit(client, '/search', {'q': malicious, 'engine': 'exact'}).json()['data']
    assert data['q'] == malicious
    assert data['result']['direct'][0]['text'] == malicious
    assert 'html' not in data
    # React source escaping and absence of executable nodes are browser/component tests.




def test_search_keeps_free_queries_and_custom_filter_spellings(client, library):
    values = {'q': 'How does "care" shape memory?', 'subject': 'an emerging subject', 'form': 'a new form', 'book': 'Unknown title', 'author': 'José García, Jr.'}
    data = submit(client, '/search', {**values, 'engine': 'exact'}).json()['data']
    assert data['q'] == values['q']
    for name, value in values.items():
        if name != 'q': assert data['filters'][name] == value
    assert next(data for name, data in library.calls if name == 'search')['filters'] == {key: value for key, value in values.items() if key != 'q'}


def test_focus_and_usage_keep_free_prose_and_choices(client, library):
    library.focus_items[0]['books'] = ['work-1']
    assert ui(client, '/focus/sunday-core')['focus']['subjects'] == ['theology']
    choices = ui(client, '/focus/sunday-core/books?q=Bodies')
    assert choices['q'] == 'Bodies'
    assert choices['focus']['books'] == ['work-1']
    assert ui(client, '/read/passage-1')['context'] == 3


@pytest.mark.parametrize("target", ["work-1", "section-1"])
def test_metadata_exposes_bounded_field_and_suggestion_choices(client, target):
    data = ui(client, f'/metadata/{target}?work=work-1')
    kinds = data['suggestion_kinds']
    assert kinds['author'] == kinds['attribution'] == 'authors'
    assert kinds['subjects'] == 'subjects'
    assert not {'title', 'notes', 'text_type'} & kinds.keys()
    assert set(data['text_types']) >= {'scripture', 'commentary', 'caption', 'mixed', 'unknown'}


@pytest.mark.parametrize("field,value,structured,expected", [
    ("subjects", '["Care, memory", "art-history", "art history"]', True, {"subjects": ["Care, memory", "art-history", "art history"]}),
    ("attribution", "José García, Jr.", False, "José García, Jr."),
    ("text_type", '"mixed"', True, "mixed"),
    ("text_type", "commentary", False, "commentary"),
])
def test_metadata_manual_and_structured_values_work_without_script(client, library, field, value, structured, expected):
    values = {"work_id": "work-1", "field": field, "value": value, "evidence": "Checked the printed source."}
    if structured:
        values["value_format"] = "json"
    response = submit(client, "/metadata/section-1", values)
    assert response.status_code == 303
    annotation = next(data for name, data in library.calls if name == "annotate")
    assert annotation["value"] == expected




@pytest.mark.parametrize("section", [False, True])
def test_bibliography_keeps_printed_name_pairs_and_field_scopes(client, library, monkeypatch, section):
    names = [{'literal': 'García, José', 'short': 'García'}, {'literal': 'A. Writer'}, {'literal': 'B. Writer', 'short': 'Writer'}]
    record = {'title': 'An Exact Title', 'year': '1998–2001', 'volume': 'IV', 'publisher': 'A & B Press', 'authors': names, 'editors': names, 'translators': names, 'type': 'chapter'}
    def bibliography_record(target_id):
        return {'id': target_id, 'work_id': 'work-1', 'work_title': library.work['title'], 'title': record['title'], 'catalog_author': 'A. Reader', 'catalog_hints': {}, 'is_section': target_id == 'section-1', 'is_passage': False, 'record': deepcopy(record)}
    monkeypatch.setattr(library, 'bibliography_record', bibliography_record, raising=False)
    data = ui(client, '/bibliography/' + ('section-1' if section else 'work-1'))
    assert data['roles'] == (['authors', 'translators'] if section else ['authors', 'editors', 'translators'])
    for role in data['roles']: assert data['target']['record'][role] == names
    assert data['target']['record']['year'] == '1998–2001'
    assert ('publisher' in data['fields']) is not section


def test_search_only_applies_explicit_filters(client, library):
    submit(client, "/search", {"q": "body ritual", "focus": "sunday-core", "engine": "exact"})
    call = next(data for name, data in library.calls if name == "search")
    assert call["filters"] is None
    assert call["focus"] == "sunday-core"
    assert call["mode"] is None
    assert call["engine"] == "exact"
    submit(client, "/search", {"q": "body", "subject": "theology", "author": "Reader", "engine": "exact"})
    assert library.calls[-1] == ("search", {"query": "body", "focus": None, "mode": None, "filters": {"subject": "theology", "author": "Reader"}, "limit": 12, "connections": 5, "engine": "exact"})


def test_explicit_breadth_overrides_focus_preference(client, library):
    response = submit(client, "/search", {"q": "body", "focus": "sunday-core", "mode": "exploratory", "engine": "exact"})
    assert response.status_code == 200
    call = next(data for name, data in library.calls if name == "search")
    assert call["mode"] == "exploratory"


@pytest.fixture
def theme_styles(client):
    from pathlib import Path
    css = (Path(__file__).parents[1] / "frontend/src/styles.css").read_text()
    light = re.search(r":root\s*\{([^}]+)\}", css).group(1)
    dark = re.search(r"@media\s*\(prefers-color-scheme:\s*dark\)\s*\{\s*:root:not\(\[data-theme\]\)\s*\{([^}]+)\}", css).group(1)
    def colors(block):
        return dict(re.findall(r"--([\w-]+):\s*(#[\da-fA-F]{6})", block))
    return css, {"light": colors(light), "dark": colors(light) | colors(dark)}


def contrast_ratio(foreground, background):
    def luminance(color):
        rgb = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in rgb]
        return sum(v * weight for v, weight in zip(linear, (.2126, .7152, .0722)))
    low, high = sorted((luminance(foreground), luminance(background)))
    return (high + .05) / (low + .05)


def test_theme_defaults_to_system_and_supports_explicit_overrides(theme_styles, client):
    css, themes = theme_styles
    assert re.search(r"color-scheme:\s*light dark", css)
    assert themes["light"]["paper"] != themes["dark"]["paper"]
    assert themes["light"]["ink"] != themes["dark"]["ink"]
    explicit = re.search(r""":root\[data-theme=['"]dark['"]\]\s*\{([^}]+)\}""", css).group(1)
    explicit_colors = dict(re.findall(r"--([\w-]+):\s*(#[\da-fA-F]{6})", explicit))
    assert all(themes["dark"][key] == value for key, value in explicit_colors.items())
    # The header and skip link need their own focus color on the oak surface.
    for selector in (".masthead :focus-visible", ".skip-link:focus"):
        rule = re.search(re.escape(selector) + r"\s*\{([^}]+)\}", css).group(1)
        assert re.search(r"outline-color:\s*var\(--brass\)", rule)


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_reading_theme_text_controls_and_focus_meet_aa(theme_styles, theme):
    _, themes = theme_styles
    colors = themes[theme]
    # Check the actual palette, allowing changes in hue without weakening contrast.
    text_pairs = [(foreground, surface)
                  for foreground in ("ink", "muted", "attribution", "teal-dark")
                  for surface in ("paper", "paper-light", "wash")]
    text_pairs += [("lede", "paper"), ("placeholder", "paper-light"),
                   ("button-ink", "teal"), ("button-ink", "teal-dark"),
                   ("paper", "ink")]
    text_pairs += [(foreground, surface)
                   for foreground in ("masthead-ink", "masthead-muted", "brass")
                   for surface in ("oak", "oak-raised")]
    ui_pairs = [(foreground, surface)
                for foreground in ("control-border", "focus")
                for surface in ("paper", "paper-light", "wash")]
    ui_pairs += [("brass", surface) for surface in ("oak", "oak-raised")]
    for pairs, minimum in ((text_pairs, 4.5), (ui_pairs, 3)):
        for foreground, background in pairs:
            ratio = contrast_ratio(colors[foreground], colors[background])
            assert ratio >= minimum, f"{theme}: {foreground} on {background} is {ratio:.2f}:1"




@pytest.mark.parametrize("headers", [{}, {"Origin": "https://evil.example"}, {"Origin": "http://127.0.0.1:8766"}])
def test_mutations_require_same_origin(client, library, headers):
    csrf = token(client)
    response = client.post("/sync", data={"csrf": csrf}, headers=headers)
    assert response.status_code == 403
    assert not any(name == "sync" for name, _ in library.calls)


def test_mutations_require_matching_csrf(client, library):
    token(client)
    response = client.post("/sync", data={"csrf": "wrong"}, headers={"Origin": ORIGIN})
    assert response.status_code == 403
    assert not any(name == "sync" for name, _ in library.calls)


def test_sync_is_explicit_post(client, library):
    assert client.get("/sync").status_code == 405
    response = submit(client, "/sync", {})
    assert response.status_code == 303
    assert response.headers["location"] == "/status?synced=true"
    assert ("sync", {}) in library.calls


def test_remote_host_is_rejected(client):
    assert client.get("/", headers={"Host": "evil.example"}).status_code == 400


@pytest.mark.parametrize("url", ["/api/search?q=x&limit=500", "/api/search?q=x&connections=100", "/api/books?offset=-1", "/api/read/passage-1?context=99", "/api/search?q=x&mode=unknown"])
def test_json_api_is_bounded(client, url):
    response = client.get(url)
    assert response.status_code == 400
    assert "error" in response.json()


def test_profile_correction_patches_only_one_facet_then_syncs(client, library):
    response = submit(client, "/metadata/work-1", {"work_id": "work-1", "field": "subjects", "value": "ritual, bodies", "evidence": "Chapter title and first paragraph."})
    assert response.status_code == 303
    annotation = next(data for name, data in library.calls if name == "annotate")
    assert annotation == {"target_id": "work-1", "field": "profile", "value": {"subjects": ["ritual", "bodies"]}, "evidence": "Chapter title and first paragraph.", "origin": "user", "status": "confirmed"}
    assert library.calls[-1] == ("sync", {})


def test_section_correction_checks_parent_and_supported_fields(client, library):
    response = submit(client, "/metadata/section-1", {"work_id": "work-1", "field": "author", "value": "New author", "evidence": "Title page"})
    assert response.status_code == 400
    assert not any(name == "annotate" for name, _ in library.calls)
    response = submit(client, "/metadata/section-1", {"work_id": "work-1", "field": "attribution", "value": "C. Writer", "evidence": "Section title page"})
    assert response.status_code == 303


def test_focus_preserves_unedited_relationships(client, library):
    library.focus_items[0]["books"] = ["work-1", "work-200"]
    response = submit(client, "/focus/sunday-core", {"name": "Sunday Thread", "description": "New description", "subjects": "theology\nart", "forms": "essay", "breadth": "exploratory"})
    assert response.status_code == 303
    saved = next(data for name, data in library.calls if name == "save_focus")
    assert saved["related_subjects"] == ["poetry"]
    assert saved["subjects"] == ["theology", "art"]
    assert saved["books"] == ["work-1", "work-200"]


def test_usage_is_explicit_and_distinguishes_inspected_from_used(client, library):
    response = submit(client, "/usage", {"passage_id": "passage-1", "purpose": "class-prep", "kind": "inspected", "notes": "Potential angle", "destination": "Proper 25"})
    assert response.status_code == 303
    record = next(data for name, data in library.calls if name == "record_usage")
    assert record["kind"] == "inspected"
    assert record["evidence"] == "Potential angle"
    assert record["work_id"] == "work-1"


def test_paid_semantic_query_requires_protected_post(client, library):
    ui(client, '/search?q=ritual&engine=openai')
    assert not any(name == 'search' for name, _ in library.calls)
    response = client.post('/api/ui/search', json={'fields': {'q': 'ritual', 'engine': ''}}, headers={'Origin': ORIGIN})
    assert response.status_code == 403
    response = client.post('/api/ui/search', json={'fields': {'q': 'ritual', 'engine': '', 'mode': 'balanced'}}, headers={'Origin': ORIGIN, 'X-CSRF-Token': token(client)})
    assert response.status_code == 200
    searches = [data for name, data in library.calls if name == 'search']
    assert 'engine' not in searches[-1]
    assert response.json()['data']['engine'] == ''


def test_search_links_and_context_controls_preserve_match_offset(client, library, monkeypatch):
    library.hit['read_offset'] = 41000
    assert submit(client, '/search', {'q': 'ritual', 'engine': 'exact'}).json()['data']['result']['direct'][0]['read_offset'] == 41000
    original = library.read
    def read(passage_id, context=3, offset=0):
        result = original(passage_id, context); result['offset'] = offset; return result
    monkeypatch.setattr(library, 'read', read)
    assert ui(client, '/read/passage-1?offset=41000')['reading']['offset'] == 41000


def test_large_form_rejected_without_mutation(client, library):
    csrf = token(client)
    response = client.post("/sync", content=urlencode({"csrf": csrf, "text": "x" * 33000}), headers={"Origin": ORIGIN, "Content-Type": "application/x-www-form-urlencoded"})
    assert response.status_code == 413
    assert not any(name == "sync" for name, _ in library.calls)


def test_failures_do_not_echo_exception_details(library):
    def broken():
        raise RuntimeError("secret=/private/api-key")
    library.status = broken
    with TestClient(create_app(library), base_url=ORIGIN, raise_server_exceptions=False) as client:
        response = client.get("/api/ui/status")
    assert response.status_code == 500
    assert "/private/api-key" not in response.text
    assert "could not finish" in response.text


def test_reader_rebuilds_bounded_structured_tables_and_keeps_note_refs(client, library):
    original_read = library.read
    def table_read(passage_id, context=3):
        reading = original_read(passage_id, context)
        reading['blocks'][0].update(kind='table', cells=[{'row': 0, 'text': 'Name', 'is_header': True}, {'row': 1, 'text': '<script>bad()</script>', 'colspan': 10000}], note_refs=[{'type': 'footnote', 'id': '7', 'target': {'member': 'word/footnotes.xml'}}], image_refs=['image-1'])
        return reading
    library.read = table_read
    block = ui(client, '/read/passage-1')['reading']['blocks'][0]
    assert block['table_rows'][0][0]['is_header'] is True
    assert block['table_rows'][1][0]['colspan'] == 100
    assert block['table_rows'][1][0]['text'] == '<script>bad()</script>'
    assert block['note_refs'][0]['id'] == '7'
    assert block['image_refs'] == ['image-1']


def test_book_contents_pagination_and_bounded_json(client, library):
    library.work['sections'] = [{'id': f'section-{i}', 'title': f'Section {i}', 'passage_id': f'passage-{i}', 'count': 1} for i in range(205)]
    work = ui(client, '/books/work-1?section_offset=100')['work']
    assert len(work['sections']) == 100
    assert work['previous_section_offset'] == 0 and work['next_section_offset'] == 200
    data = client.get('/api/books/work-1?section_offset=200&section_limit=20').json()
    assert len(data['sections']) == 5 and data['sections_total'] == 205
    assert client.get('/api/books/work-1?section_limit=1000').status_code == 400


def test_section_edits_work_beyond_first_contents_page(client, library):
    library.work["sections"] = [{"id": f"section-{i}", "title": f"Section {i}", "passage_id": None, "count": 1} for i in range(205)]
    page = "/metadata/section-150?work=work-1&section_offset=100"
    assert client.get("/api/ui" + page).status_code == 200
    response = submit(client, "/metadata/section-150", {"work_id": "work-1", "section_offset": "100", "field": "attribution", "value": "B. Writer", "evidence": "Chapter title page"}, page=page)
    assert response.status_code == 303
    assert "section_offset=100" in response.headers["location"]
    assert next(data for name, data in library.calls if name == "annotate")["target_id"] == "section-150"


def test_preferred_book_pages_preserve_selections_elsewhere(client, library):
    library.focus_items[0]["books"] = ["work-1", "work-200"]
    response = submit(client, "/focus/sunday-core/books", {"q": "", "offset": "0"})
    assert response.status_code == 303
    assert library.focus_items[0]["books"] == ["work-200"]
    response = submit(client, "/focus/sunday-core/books", {"q": "Bodies", "offset": "0", "books": "work-1"})
    assert response.status_code == 303
    assert library.focus_items[0]["books"] == ["work-200", "work-1"]
    assert "q=Bodies" in response.headers["location"]
    assert library.focus_items[0]["related_subjects"] == ["poetry"]


def test_preferred_book_editor_rejects_unlisted_choices(client, library):
    response = submit(client, "/focus/sunday-core/books", {"q": "", "offset": "0", "books": "work-unlisted"})
    assert response.status_code == 400
    assert not any(name == "save_focus" for name, _ in library.calls)


def test_preferred_book_search_and_pagination_are_bounded(client, library):
    def many_books(query='', facet=None, limit=50, offset=0):
        library.calls.append(('books', {'query': query, 'limit': limit, 'offset': offset}))
        return [{'id': f'work-{i}', 'title': f'Book {i}', 'author': 'A. Reader'} for i in range(offset, min(offset+limit, 1000))]
    library.books = many_books
    data = ui(client, '/focus/sunday-core/books?q=poetry&offset=500')
    assert len(data['books']) == 50
    assert library.calls[-1] == ('books', {'query': 'poetry', 'limit': 50, 'offset': 500})
    assert 'offset=550' in data['next_url'] and 'offset=450' in data['previous_url']
