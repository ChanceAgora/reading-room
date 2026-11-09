"""Complete, read-only text extraction with source locators for DOCX and EPUB."""

from __future__ import annotations

import posixpath
import re
import stat
from pathlib import Path
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET
import zipfile

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
V = "{urn:schemas-microsoft-com:vml}"
EPUB = "{http://www.idpf.org/2007/ops}"
OPF = "{http://www.idpf.org/2007/opf}"
CONTAINER = "{urn:oasis:names:tc:opendocument:xmlns:container}"
REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
MAX_XML_BYTES = 256 * 1024 * 1024
HTML_BLOCKS = {
    "body", "div", "section", "article", "main", "aside", "nav", "header", "footer",
    "p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "ul", "ol", "dl", "dt",
    "dd", "blockquote", "pre", "figure", "figcaption", "table", "tr", "td", "th",
    "thead", "tbody", "tfoot", "address",
}
IGNORED_HTML = {"script", "style", "head", "template"}


class ExtractionError(ValueError):
    """The package cannot be read safely or its required structure is invalid."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ExtractionError(message)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _normalized(text: str) -> str:
    return " ".join(text.split())


def _safe_member(name: str) -> None:
    _require(bool(name) and len(name) < 4096, "Invalid ZIP member name")
    _require(not name.startswith("/") and not re.match(r"^[A-Za-z]:", name), "Absolute ZIP member path")
    _require("\\" not in name and "\x00" not in name, "Unsafe ZIP member path")
    _require(all(part not in ("", ".", "..") for part in name.rstrip("/").split("/")), "Unsafe ZIP member path")


def _resolve(member: str, href: str) -> dict | None:
    uri = urlsplit(href)
    if uri.scheme or uri.netloc:
        return None
    path = unquote(uri.path, errors="strict")
    _require(not path.startswith("/") and "\\" not in path and "\x00" not in path,
             "Unsafe package resource reference")
    target = posixpath.normpath(posixpath.join(posixpath.dirname(member), path)) if path else member
    _safe_member(target)
    result = {"member": target}
    if uri.fragment:
        result["element_id"] = unquote(uri.fragment, errors="strict")
    return result


class _Package:
    def __init__(self, path: Path):
        self.zip = zipfile.ZipFile(path)
        try:
            infos = self.zip.infolist()
            names = [info.filename for info in infos]
            _require(len(infos) <= 100000, "ZIP member limit exceeded")
            _require(len(names) == len(set(names)), "Duplicate ZIP member names")
            _require(sum(info.file_size for info in infos) <= 4 * 1024**3, "ZIP expanded-size limit exceeded")
            for info in infos:
                _safe_member(info.filename)
                _require(not info.flag_bits & 1, "Encrypted ZIP member")
                _require(not stat.S_ISLNK(info.external_attr >> 16), "ZIP symlink member")
            self.names = set(names)
        except Exception:
            self.zip.close()
            raise

    def xml(self, member: str) -> ET.Element:
        _safe_member(member)
        _require(member in self.names, f"Missing package member: {member}")
        _require(self.zip.getinfo(member).file_size <= MAX_XML_BYTES, f"XML member too large: {member}")
        raw = self.zip.read(member)
        _require(b"<!ENTITY" not in raw.upper(), "XML entity declarations are unsupported")
        try:
            return ET.fromstring(raw)
        except ET.ParseError as error:
            raise ExtractionError(f"Invalid XML in {member}: {error}") from error

    def relationships(self, member: str) -> dict:
        path = posixpath.join(posixpath.dirname(member), "_rels", posixpath.basename(member) + ".rels")
        if path not in self.names:
            return {}
        result = {}
        for rel in self.xml(path).findall(REL + "Relationship"):
            key = rel.get("Id")
            _require(key and key not in result, "Missing or duplicate relationship ID")
            href = rel.get("Target", "")
            target = None if rel.get("TargetMode") == "External" else _resolve(member, href)
            result[key] = {"href": href, "target": target, "type": rel.get("Type", "")}
        return result


class _Output:
    def __init__(self, fmt: str):
        self.metadata = {"format": fmt, "identity_verified": False}
        self.blocks: list[dict] = []
        self.warnings: list[str] = []
        self.images: dict[str, dict] = {}
        self.headings: list[tuple[int, str]] = []
        self.page: str | None = None

    def warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    def image(self, member: str, alt: str | None = None, media_type: str | None = None) -> str:
        item = self.images.setdefault(member, {"member": member, "alt_texts": [], "referenced_by": []})
        if alt and alt not in item["alt_texts"]:
            item["alt_texts"].append(alt)
        if media_type:
            item["media_type"] = media_type
        return member

    def emit(self, kind: str, text: str, locator: dict, *, level: int | None = None,
             note_refs: list | None = None, image_refs: list | None = None, **extra) -> dict:
        if kind == "heading" and text.strip():
            level = level or 1
            self.headings = [(n, label) for n, label in self.headings if n < level]
            self.headings.append((level, text))
        loc = dict(locator)
        if self.page is not None and "page" not in loc:
            loc["page"] = self.page
        block = {"ordinal": len(self.blocks), "kind": kind, "text": text,
                 "search_text": _normalized(text), "heading_path": [label for _, label in self.headings],
                 "locator": loc, "note_refs": note_refs or [], "image_refs": list(dict.fromkeys(image_refs or [])),
                 "is_boilerplate": False, **extra}
        if level is not None:
            block["level"] = level
        self.blocks.append(block)
        for ref in block["image_refs"]:
            self.images[ref]["referenced_by"].append(block["ordinal"])
        return block

    def finish(self) -> dict:
        # Mark only the identifiable Bookshare wrapper, not ordinary copyright pages.
        for end, block in enumerate(self.blocks[:300]):
            if block["text"].strip().casefold() != "begin content":
                continue
            starts = [i for i, b in enumerate(self.blocks[:end]) if b["text"].strip() == "NOTICE"]
            if starts and any("bookshare" in b["text"].casefold() for b in self.blocks[starts[-1]:end]):
                # The export's repeated title and author lines precede NOTICE.
                # Begin Content is the verified boundary of the actual source.
                for item in self.blocks[:end + 1]:
                    item["is_boilerplate"] = True
                headings = []
                for item in self.blocks[end + 1:]:
                    if item.get("locator", {}).get("note_id") or item.get("supplemental"):
                        headings = []
                    if item["kind"] == "heading" and not item["is_boilerplate"]:
                        level = item.get("level") or 1
                        headings = [(n, title) for n, title in headings if n < level]
                        headings.append((level, item["text"]))
                    item["heading_path"] = [title for _, title in headings]
                break
        if not any(block["text"].strip() for block in self.blocks):
            self.warn("No readable text was found; blank or image-only source parts are preserved.")
        return {"metadata": self.metadata, "blocks": self.blocks,
                "warnings": self.warnings, "images": list(self.images.values())}


class _Docx:
    def __init__(self, package: _Package, output: _Output):
        self.package, self.out = package, output
        self.styles = {}
        self.relationships = {}
        self.paragraphs: dict[str, int] = {}
        self.tables: dict[str, int] = {}
        self.media_types = {}
        self.bookmark_paragraphs = {}
        if "[Content_Types].xml" in package.names:
            for node in package.xml("[Content_Types].xml"):
                self.media_types[node.get("PartName", "").lstrip("/") or node.get("Extension", "")] = node.get("ContentType")
        if "word/styles.xml" in package.names:
            for node in package.xml("word/styles.xml").iter(W + "style"):
                self.styles[node.get(W + "styleId")] = node

    def style(self, paragraph: ET.Element) -> tuple[int | None, str]:
        style = paragraph.find(W + "pPr/" + W + "pStyle")
        style_id = style.get(W + "val", "") if style is not None else ""
        outline = paragraph.find(W + "pPr/" + W + "outlineLvl")
        label = style_id
        seen = set()
        current = style_id
        while current in self.styles and current not in seen:
            seen.add(current)
            node = self.styles[current]
            name = node.find(W + "name")
            if current == style_id and name is not None:
                label = name.get(W + "val", label)
            if outline is None:
                outline = node.find(W + "pPr/" + W + "outlineLvl")
            parent = node.find(W + "basedOn")
            current = parent.get(W + "val", "") if parent is not None else ""
        if outline is not None:
            try:
                value = int(outline.get(W + "val", "9"))
                if 0 <= value < 9:
                    return value + 1, label
            except ValueError:
                pass
        match = re.search(r"heading\s*([1-9])", label, re.I)
        if match:
            return int(match.group(1)), label
        return (1 if label.casefold() == "title" else None), label

    def navigation_heading(self, paragraph: ET.Element, bookmarks: list[str]) -> dict | None:
        """Recover headings whose native TOC navigation survived lost Word styles."""
        text = _normalized("".join(n.text or "" for n in paragraph.iter(W + "t")))
        if not text or len(text) > 200 or not bookmarks or any(b.lower().startswith("toc") for b in bookmarks):
            return None
        for link in paragraph.iter(W + "hyperlink"):
            anchor = link.get(W + "anchor", "")
            if not anchor.lower().startswith("toc") or _normalized("".join(n.text or "" for n in link.iter(W + "t"))) != text:
                continue
            runs = [r for r in link.iter(W + "r") if r.find(W + "t") is not None]
            emphasized = bool(runs) and all(any(
                r.find(W + "rPr/" + W + tag) is not None and
                r.find(W + "rPr/" + W + tag).get(W + "val", "true") not in ("0", "false", "off")
                for tag in ("b", "i")) for r in runs)
            toc = self.bookmark_paragraphs.get(anchor)
            reciprocal = toc is not None and any(h.get(W + "anchor") in bookmarks for h in toc.iter(W + "hyperlink"))
            if reciprocal:
                reciprocal = _normalized("".join(n.text or "" for n in toc.iter(W + "t"))) == text
            # This precise split-export convention is observed in Luke Vol. 2;
            # emphasized text alone is never enough to invent a heading.
            match = re.fullmatch(r"toc-ch(\d+)(?:s(\d+))?", anchor, re.I)
            convention = bool(match and any(re.fullmatch(
                rf"chap0*{int(match[1])}-" + (rf"s{int(match[2])}" if match[2] else rf"chap0*{int(match[1])}"), b, re.I
            ) for b in bookmarks))
            if reciprocal or (convention and emphasized and toc is None and link.get(R + "id")):
                return {"origin": "reciprocal_toc" if reciprocal else "split_export_toc_convention",
                        "provisional": not reciprocal, "toc_bookmark": anchor,
                        "level": 2 if match and match[2] else 1}
        return None

    def inline(self, node: ET.Element, member: str, locator: dict) -> tuple[list, list, list, list]:
        tokens, refs, images, links = [], [], [], []
        if member not in self.relationships:
            self.relationships[member] = self.package.relationships(member)
        rels = self.relationships[member]

        def visit(element):
            if element.tag in (W + "del", W + "moveFrom"):
                return
            if element.tag in (W + "t", "{http://schemas.openxmlformats.org/officeDocument/2006/math}t"):
                tokens.append(element.text or "")
                return
            if element.tag == W + "tab":
                tokens.append("\t")
            elif element.tag in (W + "br", W + "cr", W + "lastRenderedPageBreak"):
                if element.tag == W + "lastRenderedPageBreak" or element.get(W + "type") == "page":
                    tokens.append({"layout_break": True, "rendered": element.tag == W + "lastRenderedPageBreak"})
                else:
                    tokens.append("\n")
            elif element.tag == W + "noBreakHyphen":
                tokens.append("\u2011")
            elif element.tag == W + "softHyphen":
                tokens.append("\u00ad")
            elif element.tag in (W + "footnoteReference", W + "endnoteReference"):
                note_type = "footnote" if element.tag == W + "footnoteReference" else "endnote"
                note_id = element.get(W + "id")
                refs.append({"type": note_type, "id": note_id,
                             "target": {"member": f"word/{note_type}s.xml", "note_id": note_id}})
            elif element.tag == W + "hyperlink":
                rel = rels.get(element.get(R + "id"), {})
                target = rel.get("target")
                if element.get(W + "anchor"):
                    target = dict(target or ({"external_href": rel["href"]} if rel.get("href") else {"member": member}),
                                  bookmark=element.get(W + "anchor"))
                links.append({"label": "".join(n.text or "" for n in element.iter(W + "t")),
                              "href": rel.get("href"), "target": target})
            elif element.tag in (A + "blip", V + "imagedata"):
                key = element.get(R + "embed") or element.get(R + "link") or element.get(R + "id")
                rel = rels.get(key, {})
                target = rel.get("target")
                if target:
                    image_member = target["member"]
                    if image_member not in self.package.names:
                        self.out.warn(f"Missing referenced image: {image_member}")
                    media_type = self.media_types.get(image_member) or self.media_types.get(image_member.rsplit(".", 1)[-1])
                    images.append(self.out.image(image_member, media_type=media_type))
                else:
                    self.out.warn(f"External or unresolved Word image reference in {member}; no image was fetched.")
            for child in element:
                visit(child)

        visit(node)
        alt_texts = [n.get("descr") or n.get("title") for n in node.iter(WP + "docPr")]
        if len(images) == 1:
            for alt in alt_texts:
                self.out.image(images[0], alt=alt)
        return tokens, refs, images, links

    def paragraph(self, paragraph: ET.Element, member: str, note_id: str | None = None,
                  cell: dict | None = None) -> dict:
        self.paragraphs[member] = self.paragraphs.get(member, 0) + 1
        locator = {"member": member, "paragraph": self.paragraphs[member]}
        bookmarks = [n.get(W + "name") for n in paragraph.iter(W + "bookmarkStart") if n.get(W + "name")]
        if bookmarks:
            locator["bookmark"] = bookmarks[0]
        if note_id is not None:
            locator["note_id"] = note_id
        if cell:
            locator.update(cell)
        tokens, refs, images, links = self.inline(paragraph, member, locator)
        level, style = self.style(paragraph)
        heading_evidence = self.navigation_heading(paragraph, bookmarks) if not level and not note_id else None
        if heading_evidence:
            level = heading_evidence["level"]
        kind = "heading" if level else "paragraph"
        if re.search(r"poem|poetry|stanza", style, re.I):
            kind = "poem"
        elif "caption" in style.casefold():
            kind = "caption"
        if note_id is not None:
            kind, level = "note", None
        text = "".join(token if isinstance(token, str) else "\n" for token in tokens)
        return {"kind": kind, "text": text, "locator": locator, "level": level,
                "note_refs": refs, "image_refs": images, "links": links,
                "bookmarks": bookmarks, "tokens": tokens,
                **({"heading_evidence": heading_evidence} if heading_evidence else {})}

    def emit_paragraph(self, parsed: dict) -> None:
        tokens = parsed.pop("tokens")
        breaks = any(isinstance(token, dict) for token in tokens)
        if not breaks:
            if parsed["text"] or parsed["image_refs"] or parsed["note_refs"]:
                if not parsed["text"] and parsed["image_refs"]:
                    parsed["kind"] = "image"
                self.out.emit(**parsed)
            return
        segment, number = [], 0
        for token in [*tokens, {"end": True}]:
            if isinstance(token, str):
                segment.append(token)
                continue
            if segment:
                data = dict(parsed, text="".join(segment), locator=dict(parsed["locator"], segment=number))
                self.out.emit(**data)
                segment = []
                number += 1
            if token.get("layout_break"):
                self.out.emit("pagebreak", "", dict(parsed["locator"], break_type="layout", segment=number),
                              printed_page=False, rendered_break=token["rendered"])

    def table(self, node: ET.Element, member: str, note_id: str | None = None) -> None:
        self.tables[member] = self.tables.get(member, 0) + 1
        table_number = self.tables[member]
        rows, cells, refs, images, links = [], [], [], [], []
        for row_number, tr in enumerate(node.findall(W + "tr")):
            row_text, column = [], 0
            for tc in tr.findall(W + "tc"):
                span = tc.find(W + "tcPr/" + W + "gridSpan")
                colspan = int(span.get(W + "val", "1")) if span is not None else 1
                merge = tc.find(W + "tcPr/" + W + "vMerge")
                location = {"table": table_number, "row": row_number, "column": column}
                paragraphs = [self.paragraph(p, member, note_id, location) for p in tc.iter(W + "p")]
                text = "\n".join(p["text"] for p in paragraphs)
                row_text.append(text)
                cells.append({"row": row_number, "column": column, "colspan": colspan,
                              "vertical_merge": merge.get(W + "val", "continue") if merge is not None else None,
                              "text": text, "locators": [p["locator"] for p in paragraphs]})
                for p in paragraphs:
                    refs.extend(p["note_refs"]); images.extend(p["image_refs"]); links.extend(p["links"])
                column += colspan
            rows.append("\t".join(row_text))
        locator = {"member": member, "table": table_number}
        if note_id is not None:
            locator["note_id"] = note_id
        self.out.emit("table", "\n".join(rows), locator, note_refs=refs, image_refs=images,
                      cells=cells, links=links, table_text_delimiters={"cell": "\t", "row": "\n"})

    def walk(self, node: ET.Element, member: str, note_id: str | None = None) -> None:
        for child in node:
            if child.tag == W + "p":
                self.emit_paragraph(self.paragraph(child, member, note_id))
            elif child.tag == W + "tbl":
                self.table(child, member, note_id)
            elif child.tag not in (W + "sectPr", W + "del", W + "moveFrom"):
                self.walk(child, member, note_id)

    def extract(self) -> None:
        if "docProps/core.xml" in self.package.names:
            properties = {_local(n.tag): n.text for n in self.package.xml("docProps/core.xml") if n.text}
            self.out.metadata.update(package_properties=properties, metadata_member="docProps/core.xml")
            if properties.get("title"):
                self.out.metadata["title"] = properties["title"]
        member = "word/document.xml"
        document = self.package.xml(member)
        _require(document.tag == W + "document", "Invalid Word document root")
        body = document.find(W + "body")
        _require(body is not None, "Missing Word document body")
        self.bookmark_paragraphs = {n.get(W + "name"): p for p in body.iter(W + "p")
                                    for n in p.iter(W + "bookmarkStart") if n.get(W + "name")}
        self.walk(body, member)
        for note_type in ("footnote", "endnote"):
            member = f"word/{note_type}s.xml"
            if member not in self.package.names:
                continue
            for note in self.package.xml(member):
                if note.get(W + "type", "normal") != "normal":
                    continue
                self.out.headings, self.out.page = [], None
                self.walk(note, member, note.get(W + "id"))
        self.out.metadata["coverage"] = {"body": True, "tables": True, "footnotes": True,
                                         "endnotes": True, "headers_footers": False, "image_text": False}
        if any(n.startswith(("word/header", "word/footer")) and n.endswith(".xml") for n in self.package.names):
            self.out.warn("Word headers and footers were not indexed; layout page breaks are not printed page numbers.")


def _html_types(node: ET.Element) -> set[str]:
    return set((node.get(EPUB + "type", "") + " " + node.get("role", "")).split())


def _is_note(node: ET.Element) -> bool:
    return bool(_html_types(node) & {"footnote", "endnote", "doc-footnote", "doc-endnote"})


def _is_page(node: ET.Element) -> bool:
    return bool(_html_types(node) & {"pagebreak", "doc-pagebreak"})


class _Epub:
    def __init__(self, package: _Package, output: _Output):
        self.package, self.out = package, output
        self.note_targets: set[tuple[str, str]] = set()
        self.page_labels: dict[tuple[str, str], str] = {}
        self.positions: dict[str, int] = {}
        self.media_types: dict[str, str] = {}

    def location(self, member: str, node: ET.Element, inherited_id: str | None) -> dict:
        result = {"member": member, "element_ordinal": self.positions[member]}
        element_id = node.get("id") or node.get(XML_ID) or inherited_id
        if element_id:
            result["element_id"] = element_id
        return result

    def inline(self, node: ET.Element, member: str, preserve: bool = False) -> tuple[list, list, list, list]:
        tokens, refs, images, links = [], [], [], []

        def plain(text):
            return text if preserve else re.sub(r"[\t\r\n ]+", " ", text)

        def visit(element):
            tag = _local(element.tag)
            if tag in IGNORED_HTML:
                return
            if _is_page(element):
                element_id = element.get("id") or element.get(XML_ID)
                label = element.get("aria-label") or element.get("title") or _normalized("".join(element.itertext()))
                label = label or self.page_labels.get((member, element_id))
                tokens.append({"page": label, "element_id": element_id})
                return
            nested_block = element is not node and tag in HTML_BLOCKS
            if nested_block:
                tokens.append("\n")
            if tag == "br":
                tokens.append("\n")
            if tag in ("img", "image"):
                href = element.get("src") or element.get("href") or element.get("{http://www.w3.org/1999/xlink}href")
                if href:
                    target = _resolve(member, href)
                    if target:
                        image_member = target["member"]
                        images.append(self.out.image(image_member, element.get("alt"), self.media_types.get(image_member)))
                        if image_member not in self.package.names:
                            self.out.warn(f"Missing referenced image: {image_member}")
                    else:
                        self.out.warn(f"External EPUB image in {member} was not fetched.")
            if tag == "a" and element.get("href"):
                href = element.get("href")
                target = _resolve(member, href)
                label = _normalized("".join(element.itertext()))
                links.append({"href": href, "label": label, "target": target})
                if _html_types(element) & {"noteref", "doc-noteref"} or (target and (target["member"], target.get("element_id")) in self.note_targets):
                    refs.append({"type": "note", "id": target.get("element_id") if target else None,
                                 "label": label, "target": target, "href": href})
            if element.text:
                tokens.append(plain(element.text))
            for child in element:
                visit(child)
                if child.tail:
                    tokens.append(plain(child.tail))
            if nested_block:
                tokens.append("\n")

        visit(node)
        return tokens, refs, images, links

    def emit_inline(self, node: ET.Element, member: str, inherited_id: str | None, *,
                    kind: str, preserve: bool, supplemental: bool, note_id: str | None,
                    level: int | None = None, is_navigation: bool = False) -> None:
        tokens, refs, images, links = self.inline(node, member, preserve)
        locator = self.location(member, node, inherited_id)
        if note_id:
            locator["note_id"] = note_id
        segment, number = [], 0
        for token in [*tokens, {"end": True}]:
            if isinstance(token, str):
                segment.append(token)
                continue
            text = "".join(segment)
            text = text.strip(" \t\r\n") if not preserve else text.strip("\r\n")
            if text or (number == 0 and (images or refs)):
                block = self.out.emit(kind if text else "image", text,
                                      dict(locator, segment=number) if number else locator,
                                      level=level, note_refs=refs, image_refs=images, links=links,
                                      supplemental=supplemental, is_navigation=is_navigation)
                if is_navigation:
                    block["is_boilerplate"] = True
                number += 1
            segment = []
            if "page" in token:
                self.out.page = token["page"] or None
                page_loc = dict(locator)
                if token["element_id"]:
                    page_loc["element_id"] = token["element_id"]
                if token["page"]:
                    page_loc["page"] = token["page"]
                self.out.emit("pagebreak", token["page"] or "", page_loc,
                              printed_page=bool(token["page"]), supplemental=supplemental)

    def table(self, node: ET.Element, member: str, inherited_id: str | None,
              supplemental: bool, note_id: str | None) -> None:
        rows, cells, refs, images, links = [], [], [], [], []
        for row_number, tr in enumerate(n for n in node.iter() if _local(n.tag) == "tr"):
            row_text, column = [], 0
            for cell in (n for n in tr if _local(n.tag) in ("td", "th")):
                tokens, nr, ir, ls = self.inline(cell, member)
                text = "".join(t if isinstance(t, str) else "\n" for t in tokens).strip()
                colspan, rowspan = int(cell.get("colspan", "1")), int(cell.get("rowspan", "1"))
                locator = self.location(member, cell, inherited_id)
                locator.update(row=row_number, column=column)
                cells.append({"row": row_number, "column": column, "colspan": colspan,
                              "rowspan": rowspan, "text": text, "locator": locator,
                              "is_header": _local(cell.tag) == "th"})
                row_text.append(text); refs.extend(nr); images.extend(ir); links.extend(ls)
                column += colspan
            rows.append("\t".join(row_text))
        locator = self.location(member, node, inherited_id)
        if note_id:
            locator["note_id"] = note_id
        self.out.emit("table", "\n".join(rows), locator, cells=cells, note_refs=refs,
                      image_refs=images, links=links, supplemental=supplemental,
                      table_text_delimiters={"cell": "\t", "row": "\n"})

    def walk(self, node: ET.Element, member: str, inherited_id: str | None = None,
             *, supplemental: bool = False, note_id: str | None = None,
             poem: bool = False, navigation: bool = False) -> None:
        tag = _local(node.tag)
        if tag in IGNORED_HTML:
            return
        self.positions[member] += 1
        element_id = node.get("id") or node.get(XML_ID) or inherited_id
        if _is_note(node):
            note_id = element_id
        poem = poem or bool(re.search(r"(?:^|[\s_-])(poem|poetry|stanza|verse)(?:$|[\s_-])", node.get("class", ""), re.I))
        navigation = navigation or tag == "nav"
        if tag == "table":
            self.table(node, member, element_id, supplemental, note_id)
            return
        if tag == "svg":
            self.out.warn(f"Inline SVG in {member} was not OCRed or rendered.")
        level = int(tag[1]) if re.fullmatch(r"h[1-6]", tag) else None
        kind = "heading" if level else "paragraph"
        if not level and (poem or tag == "pre"):
            kind = "poem"
        if tag == "figcaption" or re.search(r"caption", node.get("class", ""), re.I):
            kind = "caption"
        if note_id:
            kind, level = "note", None
        child_blocks = any(_local(child.tag) in HTML_BLOCKS for child in node)
        if not child_blocks:
            preserve = poem or tag == "pre" or node.get("{http://www.w3.org/XML/1998/namespace}space") == "preserve"
            self.emit_inline(node, member, element_id, kind=kind, preserve=preserve,
                             supplemental=supplemental, note_id=note_id, level=level, is_navigation=navigation)
            return
        # Loose inline content around child blocks must retain its place in the reading order.
        buffer = ET.Element("span")
        buffer.text = node.text

        def flush():
            if buffer.text or len(buffer):
                self.emit_inline(buffer, member, element_id, kind="note" if note_id else "poem" if poem else "paragraph",
                                 preserve=poem, supplemental=supplemental, note_id=note_id, is_navigation=navigation)
            buffer.clear()

        for child in node:
            if _local(child.tag) in HTML_BLOCKS:
                flush()
                self.walk(child, member, element_id, supplemental=supplemental, note_id=note_id,
                          poem=poem, navigation=navigation)
                buffer.text = child.tail
            else:
                buffer.append(child)
        flush()

    def extract(self) -> None:
        _require(self.package.zip.read("mimetype") == b"application/epub+zip", "Invalid EPUB mimetype")
        container = self.package.xml("META-INF/container.xml")
        _require(container.tag == CONTAINER + "container", "Invalid EPUB container")
        roots = container.findall(CONTAINER + "rootfiles/" + CONTAINER + "rootfile")
        _require(bool(roots), "Missing EPUB package path")
        if "META-INF/encryption.xml" in self.package.names:
            self.out.warn("EPUB encryption metadata is present; encrypted content is not decrypted.")
        documents, order, metadata_packages = {}, [], []
        for rf in roots:
            opf = _resolve("", rf.get("full-path", ""))["member"]
            package = self.package.xml(opf)
            _require(package.tag == OPF + "package", "Invalid EPUB package root")
            metadata = package.find(OPF + "metadata")
            props = [{"name": _local(n.tag), "value": "".join(n.itertext()), "attributes": dict(n.attrib)}
                     for n in metadata] if metadata is not None else []
            metadata_packages.append({"member": opf, "properties": props})
            if "title" not in self.out.metadata:
                title = next((p["value"] for p in props if p["name"] == "title"), None)
                if title:
                    self.out.metadata["title"] = title
            manifest, spine = package.find(OPF + "manifest"), package.find(OPF + "spine")
            _require(manifest is not None and spine is not None, "Missing EPUB manifest or spine")
            items = {}
            for item in manifest.findall(OPF + "item"):
                key = item.get("id")
                _require(key and key not in items, "Missing or duplicate EPUB manifest ID")
                target = _resolve(opf, item.get("href", ""))
                items[key] = (item, target)
                if target is None:
                    self.out.warn(f"External manifest resource in {opf} was not fetched.")
                    continue
                member, media = target["member"], item.get("media-type", "")
                self.media_types[member] = media
                if media.startswith("image/"):
                    self.out.image(member, media_type=media)
                if media in ("application/xhtml+xml", "text/html"):
                    if member not in self.package.names:
                        self.out.warn(f"Missing EPUB text member: {member}")
                        continue
                    documents.setdefault(member, self.package.xml(member))
            for ref in spine.findall(OPF + "itemref"):
                _require(ref.get("idref") in items, "Missing EPUB spine item")
                item, target = items[ref.get("idref")]
                _require(target is not None, "Remote EPUB spine text is unsupported")
                member = target["member"]
                _require(member in self.package.names, f"Missing EPUB spine member: {member}")
                if item.get("media-type") == "image/svg+xml":
                    self.out.warn(f"SVG spine member {member} was not OCRed or rendered.")
                elif member not in documents:
                    self.out.warn(f"Unsupported spine media type for {member}: {item.get('media-type')}")
                if member not in [m for m, _ in order]:
                    order.append((member, False))
        order.extend((member, True) for member in documents if member not in {m for m, _ in order})
        for member, document in documents.items():
            for node in document.iter():
                element_id = node.get("id") or node.get(XML_ID)
                if element_id and _is_note(node):
                    self.note_targets.add((member, element_id))
                if _local(node.tag) == "nav" and "page-list" in _html_types(node):
                    for link in node.iter():
                        if _local(link.tag) == "a" and link.get("href"):
                            target = _resolve(member, link.get("href"))
                            if target and target.get("element_id"):
                                self.page_labels[(target["member"], target["element_id"])] = _normalized("".join(link.itertext()))
        for member, supplemental in order:
            if member not in documents:
                if self.media_types.get(member, "").startswith("image/"):
                    self.out.emit("image", "", {"member": member}, image_refs=[member], supplemental=supplemental)
                continue
            document = documents[member]
            _require(_local(document.tag) == "html", f"Invalid XHTML document: {member}")
            body = next((n for n in document if _local(n.tag) == "body"), None)
            _require(body is not None, f"Missing XHTML body: {member}")
            if supplemental:
                self.out.headings, self.out.page = [], None
            self.positions[member] = 0
            self.walk(body, member, supplemental=supplemental)
        self.out.metadata.update(packages=metadata_packages, spine_members=[m for m, extra in order if not extra],
                                 supplemental_members=[m for m, extra in order if extra],
                                 coverage={"spine_text": True, "manifest_supplemental_text": True,
                                           "tables": True, "image_text": False})


def extract_file(path: Path) -> dict:
    """Extract all supported text blocks; never mutate a source or read image bytes.

    Paragraph/element ordinals are navigation locators, not printed pages.
    ``locator.page`` is present only for an explicitly labelled EPUB page marker.
    Package metadata is unverified bibliographic evidence. Fatal structural or
    unsafe-package errors raise ``ExtractionError``; source coverage gaps appear
    in ``warnings``. No external resources are fetched.
    """
    try:
        package = _Package(Path(path))
        try:
            if "word/document.xml" in package.names:
                output = _Output("docx")
                _Docx(package, output).extract()
            elif "META-INF/container.xml" in package.names:
                output = _Output("epub")
                _Epub(package, output).extract()
            else:
                raise ExtractionError("Expected a DOCX or EPUB package")
            return output.finish()
        finally:
            package.zip.close()
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as error:
        raise ExtractionError(str(error)) from error
