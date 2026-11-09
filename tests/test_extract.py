import hashlib
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

from book_library.extract import ExtractionError, extract_file


W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


class ExtractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def archive(self, name, members):
        path = self.root / name
        with zipfile.ZipFile(path, "w") as archive:
            for member, data in members.items():
                archive.writestr(member, data)
        return path

    def docx(self, body, extras=None):
        members = {
            "[Content_Types].xml": '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="png" ContentType="image/png"/></Types>',
            "word/document.xml": f'<w:document xmlns:w="{W}" xmlns:r="{R}"><w:body>{body}</w:body></w:document>',
            "word/styles.xml": f'<w:styles xmlns:w="{W}"><w:style w:styleId="Heading1"><w:name w:val="heading 1"/><w:pPr><w:outlineLvl w:val="0"/></w:pPr></w:style><w:style w:styleId="Poetry"><w:name w:val="Poetry"/></w:style><w:style w:styleId="Caption"><w:name w:val="Caption"/></w:style></w:styles>',
        }
        members.update(extras or {})
        return self.archive("fixture.docx", members)

    def epub(self, documents, spine, extra_members=None, extra_manifest=""):
        items = "".join(f'<item id="d{i}" href="{name}" media-type="application/xhtml+xml"/>' for i, name in enumerate(documents))
        name_ids = {name: f"d{i}" for i, name in enumerate(documents)}
        refs = "".join(f'<itemref idref="{name_ids[name]}"/>' for name in spine)
        members = {
            "mimetype": "application/epub+zip",
            "META-INF/container.xml": '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="EPUB/package.opf" media-type="application/oebps-package+xml"/></rootfiles></container>',
            "EPUB/package.opf": '<package xmlns="http://www.idpf.org/2007/opf" version="3.0"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Publisher Title</dc:title><dc:creator>Editor Name</dc:creator></metadata><manifest>' + items + extra_manifest + '</manifest><spine>' + refs + '</spine></package>',
        }
        for name, body in documents.items():
            members["EPUB/" + name] = '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><head><title>Ignored head</title></head><body>' + body + '</body></html>'
        members.update(extra_members or {})
        return self.archive("fixture.epub", members)

    def assert_contract(self, result):
        self.assertEqual(set(result), {"metadata", "blocks", "warnings", "images"})
        self.assertEqual([b["ordinal"] for b in result["blocks"]], list(range(len(result["blocks"]))))
        for block in result["blocks"]:
            for key in ("kind", "text", "heading_path", "locator", "note_refs", "image_refs", "is_boilerplate"):
                self.assertIn(key, block)
            self.assertNotIn("attribution", block)

    def test_word_lineation_heading_table_and_citation_locators(self):
        path = self.docx(
            '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:bookmarkStart w:id="0" w:name="ch1"/><w:r><w:t>Chapter One</w:t></w:r></w:p>'
            '<w:p><w:pPr><w:pStyle w:val="Poetry"/></w:pPr><w:r><w:t xml:space="preserve">  First line</w:t><w:br/><w:t>second line</w:t><w:tab/><w:t>ending</w:t></w:r></w:p>'
            '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Left</w:t></w:r></w:p><w:p><w:r><w:t>Below</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Right</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
            '<w:p><w:pPr><w:pStyle w:val="Caption"/></w:pPr><w:r><w:t>Figure caption</w:t></w:r></w:p>'
        )
        before = hashlib.sha256(path.read_bytes()).digest()
        result = extract_file(path)
        self.assert_contract(result)
        heading, poem, table, caption = result["blocks"]
        self.assertEqual(heading["locator"]["bookmark"], "ch1")
        self.assertEqual(poem["kind"], "poem")
        self.assertEqual(poem["text"], "  First line\nsecond line\tending")
        self.assertEqual(poem["heading_path"], ["Chapter One"])
        self.assertEqual(table["text"], "Left\nBelow\tRight")
        self.assertEqual(table["cells"][1]["column"], 1)
        self.assertEqual(caption["kind"], "caption")
        self.assertEqual(before, hashlib.sha256(path.read_bytes()).digest())

    def test_word_navigation_headings_and_split_part_evidence(self):
        toc = '<w:p><w:bookmarkStart w:name="toc-ch01s1"/><w:hyperlink w:anchor="chap01-s1"><w:r><w:t>Perspective</w:t></w:r></w:hyperlink></w:p>'
        heading = '<w:p><w:bookmarkStart w:name="chap01-s1"/><w:hyperlink w:anchor="toc-ch01s1"><w:r><w:rPr><w:b/></w:rPr><w:t>Perspective</w:t></w:r></w:hyperlink></w:p>'
        body = '<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>Ordinary bold paragraph</w:t></w:r></w:p>'
        result = extract_file(self.docx(toc + heading + body))
        self.assertEqual([b['kind'] for b in result['blocks']], ['paragraph', 'heading', 'paragraph'])
        self.assertEqual(result['blocks'][1]['heading_evidence']['origin'], 'reciprocal_toc')
        self.assertEqual(result['blocks'][1]['level'], 2)
        rels = '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="back" Type="hyperlink" Target="original-part-1.docx" TargetMode="External"/></Relationships>'
        split = heading.replace('w:anchor="toc-ch01s1"', 'w:anchor="toc-ch01s1" r:id="back"')
        result = extract_file(self.docx(split + body, {'word/_rels/document.xml.rels': rels}))
        self.assertTrue(result['blocks'][0]['heading_evidence']['provisional'])
        self.assertEqual(result['blocks'][0]['links'][0]['target'], {'external_href': 'original-part-1.docx', 'bookmark': 'toc-ch01s1'})
        self.assertEqual(result['blocks'][1]['kind'], 'paragraph')
        chapter = split.replace('chap01-s1', 'chap01-chap1').replace('toc-ch01s1', 'toc-ch1').replace('<w:b/>', '<w:i/>')
        result = extract_file(self.docx(chapter + body, {'word/_rels/document.xml.rels': rels}))
        self.assertEqual(result['blocks'][0]['kind'], 'heading')
        self.assertEqual(result['blocks'][0]['level'], 1)

    def test_word_notes_keep_reference_targets_and_supplemental_order(self):
        path = self.docx(
            '<w:p><w:r><w:t>Body</w:t><w:footnoteReference w:id="2"/><w:endnoteReference w:id="7"/></w:r>'
            '<w:hyperlink w:anchor="later"><w:r><w:t> internal link</w:t></w:r></w:hyperlink></w:p>',
            {
                "word/footnotes.xml": f'<w:footnotes xmlns:w="{W}"><w:footnote w:type="separator" w:id="-1"><w:p><w:r><w:t>Not prose</w:t></w:r></w:p></w:footnote><w:footnote w:id="2"><w:p><w:r><w:t>Footnote text</w:t></w:r></w:p></w:footnote></w:footnotes>',
                "word/endnotes.xml": f'<w:endnotes xmlns:w="{W}"><w:endnote w:id="7"><w:p><w:r><w:t>Endnote text</w:t></w:r></w:p></w:endnote></w:endnotes>',
            },
        )
        blocks = extract_file(path)["blocks"]
        self.assertEqual([b["kind"] for b in blocks], ["paragraph", "note", "note"])
        self.assertEqual(blocks[0]["note_refs"][0]["target"], {"member": "word/footnotes.xml", "note_id": "2"})
        self.assertEqual(blocks[1]["locator"]["note_id"], "2")
        self.assertEqual(blocks[0]["links"][0]["target"]["bookmark"], "later")
        self.assertNotIn("Not prose", " ".join(b["text"] for b in blocks))

    def test_word_layout_break_is_not_a_printed_page(self):
        result = extract_file(self.docx('<w:p><w:r><w:t>Before</w:t><w:br w:type="page"/><w:t>After</w:t></w:r></w:p>'))
        self.assertEqual([b["kind"] for b in result["blocks"]], ["paragraph", "pagebreak", "paragraph"])
        self.assertEqual([b["text"] for b in result["blocks"]], ["Before", "", "After"])
        self.assertFalse(result["blocks"][1]["printed_page"])
        self.assertTrue(all("page" not in b["locator"] for b in result["blocks"]))

    def test_word_images_are_references_without_image_reads(self):
        path = self.docx(
            '<w:p><w:r><w:drawing xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><wp:docPr id="1" descr="A painting"/><a:blip r:embed="pic1"/></w:drawing></w:r></w:p>',
            {"word/_rels/document.xml.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="pic1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/picture.png"/></Relationships>',
             "word/media/picture.png": b"not a real image; must never be decoded"},
        )
        original = zipfile.ZipFile.read
        def text_only(archive, name, *args, **kwargs):
            self.assertFalse(str(name).endswith(".png"))
            return original(archive, name, *args, **kwargs)
        with patch.object(zipfile.ZipFile, "read", text_only):
            result = extract_file(path)
        self.assertEqual(result["blocks"][0]["kind"], "image")
        self.assertEqual(result["images"][0]["alt_texts"], ["A painting"])
        self.assertEqual(result["images"][0]["referenced_by"], [0])

    def test_epub_spine_order_lineation_and_supplemental_notes(self):
        path = self.epub(
            {
                "last.xhtml": '<h2 id="last">Later chapter</h2><p>Last body</p>',
                "first.xhtml": '<h1 id="first">First chapter</h1><div class="poem"><p id="verse">First line<br/>Second line</p></div><p>Some text<a epub:type="noteref" href="notes.xhtml#n1">1</a>.</p>',
                "notes.xhtml": '<aside epub:type="footnote" id="n1"><p>Supplemental note<a href="first.xhtml#first">back</a></p></aside>',
            },
            ["first.xhtml", "last.xhtml"],
        )
        result = extract_file(path)
        self.assert_contract(result)
        blocks = result["blocks"]
        self.assertEqual(blocks[0]["text"], "First chapter")
        self.assertEqual(blocks[1]["kind"], "poem")
        self.assertEqual(blocks[1]["text"], "First line\nSecond line")
        self.assertEqual(blocks[1]["locator"]["element_id"], "verse")
        self.assertEqual(blocks[2]["note_refs"][0]["target"], {"member": "EPUB/notes.xhtml", "element_id": "n1"})
        self.assertEqual(blocks[-1]["kind"], "note")
        self.assertEqual(blocks[-1]["locator"]["note_id"], "n1")
        self.assertTrue(blocks[-1]["supplemental"])

    def test_poem_title_class_does_not_hide_real_heading(self):
        path = self.epub({"poem.xhtml": '<h1 class="poem_title" id="title">A poem title</h1><p xml:space="preserve">  First line\nSecond line</p>'}, ["poem.xhtml"])
        blocks = extract_file(path)["blocks"]
        self.assertEqual(blocks[0]["kind"], "heading")
        self.assertEqual(blocks[1]["heading_path"], ["A poem title"])
        self.assertEqual(blocks[1]["text"], "  First line\nSecond line")

    def test_epub_page_labels_split_inline_text_and_propagate_only_real_labels(self):
        path = self.epub(
            {
                "body.xhtml": '<h1>Title</h1><p>Before<span epub:type="pagebreak" id="p17" title="17"/>After</p><p>Next paragraph</p><span epub:type="pagebreak" id="p18"/><p>Following</p><span epub:type="pagebreak" id="unlabelled"/><p>Unknown page</p>',
                "nav.xhtml": '<nav epub:type="page-list"><ol><li><a href="body.xhtml#p18">18</a></li></ol></nav>',
            },
            ["body.xhtml"],
        )
        blocks = extract_file(path)["blocks"]
        self.assertEqual([b["text"] for b in blocks[:8]], ["Title", "Before", "17", "After", "Next paragraph", "18", "Following", ""])
        self.assertEqual(next(b for b in blocks if b["text"] == "After")["locator"]["page"], "17")
        self.assertEqual(next(b for b in blocks if b["text"] == "Following")["locator"]["page"], "18")
        self.assertNotIn("page", next(b for b in blocks if b["text"] == "Unknown page")["locator"])

    def test_epub_tables_links_images_and_no_remote_content(self):
        path = self.epub(
            {"body.xhtml": '<p>Intro</p><table id="tbl"><tr><th>Name</th><th>Value</th></tr><tr><td><p>A</p><p>B</p></td><td><a href="https://example.org/">Site</a></td></tr></table><figure><img src="img.png" alt="A work of art"/><figcaption>Artist, work title.</figcaption></figure><p><img src="https://example.org/remote.png"/></p><script>Excluded code</script>'},
            ["body.xhtml"], {"EPUB/img.png": b"not read"}, '<item id="image" href="img.png" media-type="image/png"/>',
        )
        original = zipfile.ZipFile.read
        def text_only(archive, name, *args, **kwargs):
            self.assertFalse(str(name).endswith(".png"))
            return original(archive, name, *args, **kwargs)
        with patch.object(zipfile.ZipFile, "read", text_only):
            result = extract_file(path)
        table = next(b for b in result["blocks"] if b["kind"] == "table")
        self.assertIn("A\n\nB", table["text"])
        self.assertEqual(table["links"][0]["href"], "https://example.org/")
        self.assertIsNone(table["links"][0]["target"])
        self.assertEqual(next(b for b in result["blocks"] if b["kind"] == "caption")["text"], "Artist, work title.")
        self.assertEqual(result["images"][0]["alt_texts"], ["A work of art"])
        self.assertTrue(any("External EPUB image" in w for w in result["warnings"]))
        self.assertNotIn("Excluded code", " ".join(b["text"] for b in result["blocks"]))

    def test_known_boilerplate_is_marked_without_dropping_it(self):
        texts = ["Export title", "Export author", "NOTICE", "Copyright Notice", "Bookshare personal copy", "Begin Content", "Real text"]
        result = extract_file(self.docx("".join(f'<w:p><w:r><w:t>{t}</w:t></w:r></w:p>' for t in texts)))
        self.assertEqual([b["text"] for b in result["blocks"]], texts)
        self.assertEqual([b["is_boilerplate"] for b in result["blocks"]], [True] * 6 + [False])

    def test_begin_content_without_bookshare_wrapper_is_not_boilerplate(self):
        texts = ["NOTICE", "Book chapter", "Begin Content", "Real text"]
        result = extract_file(self.docx("".join(f'<w:p><w:r><w:t>{t}</w:t></w:r></w:p>' for t in texts)))
        self.assertFalse(any(b["is_boilerplate"] for b in result["blocks"]))

    def test_blank_parts_are_valid_and_not_fabricated(self):
        result = extract_file(self.docx("<w:p/>"))
        self.assertEqual(result["blocks"], [])
        self.assertTrue(any("No readable text" in warning for warning in result["warnings"]))

    def test_zip_safety_and_duplicate_names(self):
        for name in ("../escape.xml", "/absolute.xml", "C:/drive.xml", "x\\bad.xml"):
            with self.subTest(name=name):
                path = self.archive("unsafe.zip", {name: "<x/>"})
                with self.assertRaises(ExtractionError):
                    extract_file(path)
        path = self.root / "duplicate.docx"
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("word/document.xml", "<x/>")
                archive.writestr("word/document.xml", "<x/>")
        with self.assertRaisesRegex(ExtractionError, "Duplicate"):
            extract_file(path)
        path = self.root / "symlink.zip"
        info = zipfile.ZipInfo("link.xml")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(info, "target")
        with self.assertRaisesRegex(ExtractionError, "symlink"):
            extract_file(path)

    def test_package_reference_traversal_is_rejected(self):
        path = self.epub({"body.xhtml": '<p><img src="../../outside.png"/></p>'}, ["body.xhtml"])
        with self.assertRaises(ExtractionError):
            extract_file(path)

    def test_xml_entities_and_missing_spine_are_reported(self):
        path = self.docx("", {"word/document.xml": '<!DOCTYPE x [<!ENTITY x "expanded">]><x>&x;</x>'})
        with self.assertRaisesRegex(ExtractionError, "entity"):
            extract_file(path)
        path = self.epub({"body.xhtml": "<p>Text</p>"}, ["body.xhtml"])
        with zipfile.ZipFile(path) as archive:
            contents = {n: archive.read(n) for n in archive.namelist() if n != "EPUB/body.xhtml"}
        path = self.archive("missing.epub", contents)
        with self.assertRaisesRegex(ExtractionError, "Missing EPUB spine member"):
            extract_file(path)


if __name__ == "__main__":
    unittest.main()
