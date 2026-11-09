"""Artwork discovery should lead to readable evidence rather than its index entry."""

import pytest
import test_extract
import zipfile

from book_library.service import Library
from test_media import PNG
from test_service import docx, seed


def test_caption_context_out_ranks_figure_list_and_loans(tmp_path):
    root = tmp_path / "books"
    artwork = "Dog with Blue Blanket"
    source = docx(root / "Art" / "Art.docx", [
        ("Heading1", "List of Figures"),
        f"1. {artwork}. 2. {artwork}, detail.",
        ("Heading1", "Loans"),
        f"{artwork}; {artwork}, detail. Loan register.",
        ("Heading1", "Domestic animals in drawing"),
        "An account of the artist's materials and family setting. " * 28
        + f"Figure 1. {artwork}. Colored pencil on paper. "
        + "The surrounding discussion explains how this drawing relates to the series. " * 12,
    ])
    lib = seed(root, [{"title": "An Art Collection", "paths": [source]}])

    # Without the reference-section adjustment, both short catalog mentions
    # consume the two-per-work result allowance and hide the usable context.
    result = lib.search(f'"{artwork}"', connections=0)
    assert len(result["direct"]) == 2
    best = result["direct"][0]
    assert best["heading"] == "Domestic animals in drawing"
    assert artwork in best["text"]
    assert "Colored pencil on paper" in best["text"]
    assert len(best["text"]) <= 702
    assert best["text"].startswith("…")

    # The centered excerpt is only a search preview; the source context survives.
    reading = lib.read(best["id"], context=0)
    context = "\n".join(block["text"] for block in reading["blocks"])
    assert "artist's materials and family setting" in context
    assert "relates to the series" in context


def test_explicit_book_filter_can_return_more_than_two_matching_sections(tmp_path):
    root = tmp_path / "books"
    sections = [
        ("Materials", "Blue pigments were prepared from local minerals."),
        ("Textiles", "Blue pigments colored the fabric around the figure."),
        ("Workshop", "Blue pigments were stored beside the grinding tools."),
        ("Conservation", "Blue pigments remain visible beneath the varnish."),
    ]
    source = docx(root / "Art" / "Art.docx", [
        item for title, text in sections for item in [("Heading1", title), text]
    ])
    other = docx(root / "Other" / "Other.docx", ["Blue pigments provide an unrelated comparison."])
    lib = seed(root, [
        {"title": "A Pigment Study", "paths": [source]},
        {"title": "Another Book", "paths": [other]},
    ])
    work_id = next(book["id"] for book in lib.books() if book["title"] == "A Pigment Study")

    general = lib.search('"blue pigments"', connections=0)
    assert sum(hit["work_id"] == work_id for hit in general["direct"]) == 2
    specific = lib.search('"blue pigments"', filters={"book": work_id}, connections=0)
    assert {hit["heading"] for hit in specific["direct"]} == {title for title, _ in sections}
    assert all(hit["work_id"] == work_id for hit in specific["direct"])

    limited = lib.search('"blue pigments"', filters={"book": work_id}, limit=3, connections=0)
    assert len(limited["direct"]) == 3


def test_match_centered_excerpt_preserves_source_diacritics(tmp_path):
    root = tmp_path / "books"
    source = docx(root / "Yoruba" / "Yoruba.docx", [
        ("Heading1", "Carving and performance"),
        "The chapter surveys carving and performance in its historical context. " * 24
        + "The ọpọ́n-Ifá is described alongside performed oríkì and verbal artistry. "
        + "Further discussion compares the local examples in detail. " * 12,
    ])
    lib = seed(root, [{"title": "Art and Language", "paths": [source]}])
    hit = lib.search("oriki", connections=0)["direct"][0]
    assert "oríkì" in hit["text"]
    assert "ọpọ́n-Ifá" in hit["text"]
    assert hit["text"].startswith("…")
    assert len(hit["text"]) <= 702


@pytest.mark.parametrize("prefix", ["e\u0301 " * 500, "\ufb03 " * 500])
def test_normalized_match_offsets_map_back_to_source_text(tmp_path, prefix):
    root = tmp_path / "books"
    sentence = "The artwork is Dog with Blue Blanket."
    source = docx(root / "Art" / "Art.docx", [
        ("Heading1", "Artwork description"),
        prefix + sentence + " Further description of the drawing." * 50,
    ])
    lib = seed(root, [{"title": "Art", "paths": [source]}])
    hit = lib.search('"Dog with Blue Blanket"', connections=0)["direct"][0]
    assert sentence in hit["text"]
    assert len(hit["text"]) <= 702


@pytest.mark.parametrize("image_first", [True, False])
def test_caption_read_keeps_adjacent_empty_alt_image_with_zero_context(tmp_path, monkeypatch, image_first):
    root = tmp_path / "books"
    root.mkdir()
    package = test_extract.ExtractTests()
    package.root = root
    image = '<img src="images/figure.png" alt=""/>'
    caption = '<p>Figure 1. Copper birds in a landscape.</p>'
    pair = image + caption if image_first else caption + image
    package.epub(
        {"chapter.xhtml": '<h1>Landscape drawings</h1><p>'
            + "The introductory discussion considers the exhibition. " * 45
            + '</p>' + pair
            + '<h1>A separate drawing</h1><p>An unrelated caption.</p>'
            + '<img src="images/unrelated.png" alt=""/>'},
        ["chapter.xhtml"],
        extra_members={"EPUB/images/figure.png": PNG, "EPUB/images/unrelated.png": PNG},
        extra_manifest='<item id="figure" href="images/figure.png" media-type="image/png"/>'
            '<item id="unrelated" href="images/unrelated.png" media-type="image/png"/>',
    )
    lib = Library(root)
    lib.sync()
    hit = lib.search('"Copper birds"', connections=0)["direct"][0]

    # Plain passage navigation must use indexed image references, not decode
    # the original archive or need a nonempty image description to keep it.
    monkeypatch.setattr(zipfile, "ZipFile", lambda *args, **kwargs: pytest.fail("Reading should not open the EPUB."))
    reading = lib.read(hit["id"], context=0)
    images = [block for block in reading["blocks"] if block.get("image_refs")]
    assert len(images) == 1
    assert images[0]["text"] == ""
    assert images[0]["image_refs"] == ["EPUB/images/figure.png"]
    assert any("Copper birds" in block["text"] for block in reading["blocks"])
    assert len(reading["blocks"]) <= 80


def test_coarse_contents_heading_does_not_demote_real_chapter_prose(tmp_path):
    root = tmp_path / "books"
    prose = "Parallelism intensifies the line through successive poetic transformations. " * 18
    first = docx(root / "A" / "A.docx", [("Heading1", "Table of Contents"), prose])
    second = docx(root / "B" / "B.docx", [("Heading1", "Discussion"), prose])
    lib = seed(root, [{"title": "A Poetics", "paths": [first]}, {"title": "B Poetics", "paths": [second]}])
    hits = lib.search("parallelism", connections=0)["direct"]
    coarse = next(hit for hit in hits if hit["title"] == "A Poetics")
    assert coarse["score"] > .015  # no reference-section penalty on substantive prose
