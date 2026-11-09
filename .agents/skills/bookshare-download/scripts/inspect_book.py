#!/usr/bin/env python3
"""Read-only, bounded inspection of Bookshare DOCX, EPUB, and download ZIPs."""

import argparse
import hashlib
import io
import json
from pathlib import Path
import posixpath
import re
import stat
import sys
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET
import zipfile

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
OPF = '{http://www.idpf.org/2007/opf}'
CONTAINER = '{urn:oasis:names:tc:opendocument:xmlns:container}'
MAX_BYTES = 512 * 1024 * 1024
MAX_MEMBERS = 10000
MAX_OUTPUT_BYTES = 256 * 1024
SNIPPET = 350
BLOCKS = {'body', 'div', 'section', 'article', 'p', 'li', 'ul', 'ol', 'dl', 'dt',
          'dd', 'blockquote', 'pre', 'figure', 'figcaption', 'table', 'thead',
          'tbody', 'tfoot', 'tr', 'td', 'th', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}
SKIP = {'script', 'style'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def local(tag):
    return tag.rsplit('}', 1)[-1]


def clean(text):
    return ' '.join(text.split())


def clip(text, limit=SNIPPET):
    return text if len(text) <= limit else text[:limit] + '…'


def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def safe_member(name):
    require(bool(name) and len(name) <= 1024, 'Empty or excessively long ZIP member name')
    require(not name.startswith('/') and not re.match(r'^[A-Za-z]:', name), 'Absolute ZIP member path')
    require('\\' not in name and '\x00' not in name, 'Unsafe ZIP member path')
    require(all(p not in ('', '.', '..') for p in name.rstrip('/').split('/')), 'Unsafe ZIP member path')


def checked_zip(raw):
    archive = zipfile.ZipFile(io.BytesIO(raw))
    try:
        infos = archive.infolist()
        require(len(infos) <= MAX_MEMBERS, 'ZIP member limit exceeded')
        names = [item.filename for item in infos]
        require(len(names) == len(set(names)), 'Duplicate ZIP member names')
        require(sum(item.file_size for item in infos) <= MAX_BYTES, 'ZIP expanded-size limit exceeded')
        for item in infos:
            safe_member(item.filename)
            require(not item.flag_bits & 1, 'Encrypted ZIP member')
            require(not stat.S_ISLNK(item.external_attr >> 16), 'ZIP symlink member')
        require(archive.testzip() is None, 'ZIP CRC check failed')
        return archive
    except Exception:
        archive.close()
        raise


def xml(raw):
    require(b'<!ENTITY' not in raw.upper(), 'XML entity declarations are unsupported')
    return ET.fromstring(raw)


def row(text, member, number, fragment=None, heading=None, note_id=None):
    result = {'text': clean(text), 'member': member, 'paragraph': number}
    if fragment:
        result['fragment'] = fragment
    if heading:
        result['heading'] = heading
    if note_id is not None:
        result['note_id'] = note_id
    return result


def word_text(node):
    pieces = []
    for child in node.iter():
        if child.tag == W + 't':
            pieces.append(child.text or '')
        elif child.tag in (W + 'tab', W + 'br', W + 'cr'):
            pieces.append(' ')
    return ''.join(pieces)


def inspect_docx(archive):
    names = archive.namelist()
    require('[Content_Types].xml' in names, 'Missing DOCX content types')
    roots = {n: xml(archive.read(n)) for n in names if n.endswith(('.xml', '.rels'))}
    require('word/document.xml' in roots, 'Missing DOCX document')
    require(roots['word/document.xml'].tag == W + 'document' and roots['word/document.xml'].find(W + 'body') is not None,
            'Invalid DOCX document root or missing body')
    metadata = {}
    metadata_omitted = 0
    if 'docProps/core.xml' in roots:
        for node in roots['docProps/core.xml']:
            if node.text:
                if len(metadata) < 24:
                    metadata[clip(local(node.tag), 80)] = clip(clean(node.text))
                else:
                    metadata_omitted += 1
    styles = {}
    for node in roots.get('word/styles.xml', ET.Element('none')).iter(W + 'style'):
        name = node.find(W + 'name')
        outline = node.find(W + 'pPr/' + W + 'outlineLvl')
        label = name.get(W + 'val', '') if name is not None else ''
        if outline is not None or re.match(r'heading|title', label, re.I):
            styles[node.get(W + 'styleId')] = label or 'Outline heading'
    paragraphs = []
    for member in ('word/document.xml', 'word/footnotes.xml', 'word/endnotes.xml'):
        if member not in roots:
            continue
        root = roots[member]
        groups = [(root, None)] if member.endswith('/document.xml') else [
            (note, note.get(W + 'id')) for note in root
            if note.get(W + 'type', 'normal') == 'normal']
        number = 0
        for group, note_id in groups:
            for paragraph in group.iter(W + 'p'):
                number += 1
                text = clean(word_text(paragraph))
                if not text:
                    continue
                style = paragraph.find(W + 'pPr/' + W + 'pStyle')
                style_id = style.get(W + 'val', '') if style is not None else ''
                heading = styles.get(style_id)
                if not heading and re.match(r'heading|title', style_id, re.I):
                    heading = style_id
                bookmarks = [b.get(W + 'name') for b in paragraph.iter(W + 'bookmarkStart')]
                paragraphs.append(row(text, member, number, next((b for b in bookmarks if b), None), heading, note_id))
    return metadata, paragraphs, {'text_sources': ['word/document.xml', 'word/footnotes.xml', 'word/endnotes.xml'],
                                  'includes_tables': True, 'metadata_values_omitted': metadata_omitted}, []


def resolve(base, reference):
    uri = urlsplit(reference)
    require(not uri.scheme and not uri.netloc and not uri.query, 'Nonlocal EPUB resource reference')
    path = unquote(uri.path, errors='strict')
    require(path and not path.startswith('/') and '\\' not in path and '\x00' not in path,
            'Unsafe EPUB resource reference')
    target = posixpath.normpath(posixpath.join(posixpath.dirname(base), path))
    safe_member(target)
    return target


def visible_text(node):
    if local(node.tag) in SKIP:
        return ''
    return (node.text or '') + ''.join(visible_text(c) + (c.tail or '') for c in node)


def html_blocks(node, fragment=None):
    """Keep text in document order, including loose text and table cells."""
    if local(node.tag) in SKIP:
        return
    fragment = node.get('id') or node.get('{http://www.w3.org/XML/1998/namespace}id') or fragment
    heading = local(node.tag) if re.fullmatch(r'h[1-6]', local(node.tag)) else None
    buffer = node.text or ''
    for child in node:
        if local(child.tag) in BLOCKS or any(local(n.tag) in BLOCKS for n in child.iter()):
            if clean(buffer):
                yield buffer, fragment, heading
            buffer = ''
            yield from html_blocks(child, fragment)
        else:
            buffer += visible_text(child)
        buffer += child.tail or ''
    if clean(buffer):
        yield buffer, fragment, heading


def inspect_epub(archive):
    require(archive.read('mimetype') == b'application/epub+zip', 'Invalid EPUB mimetype')
    container = xml(archive.read('META-INF/container.xml'))
    require(container.tag == CONTAINER + 'container', 'Invalid EPUB container')
    rootfiles = container.findall(CONTAINER + 'rootfiles/' + CONTAINER + 'rootfile')
    require(rootfiles, 'Missing EPUB package path')
    metadata, paragraphs, packages, warnings = {}, [], [], []
    metadata_omitted = 0
    if 'META-INF/encryption.xml' in archive.namelist():
        warnings.append('Encryption metadata is present; this inspector does not decrypt resources.')
    for rootfile in rootfiles:
        member = resolve('', rootfile.get('full-path', ''))
        package = xml(archive.read(member))
        require(package.tag == OPF + 'package', 'Invalid EPUB OPF root')
        md = package.find(OPF + 'metadata')
        if md is not None:
            for node in md:
                if node.text and local(node.tag) != 'meta':
                    key = clip(local(node.tag), 80)
                    if (key in metadata or len(metadata) < 24) and len(metadata.get(key, [])) < 3:
                        metadata.setdefault(key, []).append(clip(clean(node.text)))
                    else:
                        metadata_omitted += 1
        manifest, spine = package.find(OPF + 'manifest'), package.find(OPF + 'spine')
        require(manifest is not None and spine is not None, 'Missing EPUB manifest or spine')
        items = {}
        missing = []
        for item in manifest.findall(OPF + 'item'):
            key = item.get('id')
            require(key and key not in items, 'Missing or duplicate EPUB manifest ID')
            items[key] = item
            href = item.get('href', '')
            if urlsplit(href).scheme or urlsplit(href).netloc:
                warnings.append('Remote manifest resource was not fetched: ' + clip(href, 160))
            elif resolve(member, href) not in archive.namelist():
                missing.append(href)
        require(not missing, 'Missing EPUB manifest resource: ' + ', '.join(missing[:5]))
        refs = spine.findall(OPF + 'itemref')
        require(refs, 'Empty EPUB spine')
        spine_members = []
        for ref in refs:
            require(ref.get('idref') in items, 'Missing EPUB spine ID')
            item = items[ref.get('idref')]
            document_path = resolve(member, item.get('href', ''))
            document = xml(archive.read(document_path))
            spine_members.append(document_path)
            media = item.get('media-type')
            if media == 'image/svg+xml':
                require(local(document.tag) == 'svg', 'Invalid SVG spine document')
                warnings.append('SVG spine document has no extracted prose: ' + document_path)
                continue
            require(media == 'application/xhtml+xml' and local(document.tag) == 'html',
                    'Unsupported EPUB spine document type')
            body = next((n for n in document if local(n.tag) == 'body'), None)
            require(body is not None, 'Missing XHTML body')
            for number, (text, fragment, heading) in enumerate(html_blocks(body), 1):
                paragraphs.append(row(text, document_path, number, fragment, heading))
        packages.append({'member': member, 'spine_document_count': len(spine_members),
                         'spine_members': spine_members[:100], 'spine_members_omitted': max(0, len(spine_members) - 100),
                         'manifest_image_count': sum(i.get('media-type', '').startswith('image/') for i in items.values())})
    return metadata, paragraphs, {'packages': packages, 'metadata_values_omitted': metadata_omitted}, warnings


def excerpt(paragraph, query=None):
    result = dict(paragraph)
    text = result['text']
    start = 0
    if query:
        # Literal case-insensitive matching preserves the original character offsets.
        match = re.search(re.escape(query), text, flags=re.I)
        if match:
            start = max(0, match.start() - 100)
    result['text'] = ('…' if start else '') + clip(text[start:])
    result['text_truncated'] = start > 0 or len(text) > SNIPPET
    return result


def inspect_package(raw, source, args, match_budget):
    result = dict(source, **identity(raw), package_valid=False)
    try:
        with checked_zip(raw) as archive:
            if 'word/document.xml' in archive.namelist():
                result['format'] = 'docx'
                metadata, paragraphs, details, warnings = inspect_docx(archive)
            elif 'META-INF/container.xml' in archive.namelist():
                result['format'] = 'epub'
                metadata, paragraphs, details, warnings = inspect_epub(archive)
            else:
                raise ValueError('Neither DOCX nor EPUB package')
        result.update(package_valid=True, metadata=metadata, **details,
                      paragraph_count=len(paragraphs), text_characters=sum(len(p['text']) for p in paragraphs),
                      has_text=bool(paragraphs), warnings=warnings[:10], warnings_omitted=max(0, len(warnings) - 10))
        result['opening_paragraphs'] = [excerpt(p) for p in paragraphs[:5]]
        result['closing_paragraphs'] = [excerpt(p) for p in paragraphs[-3:]]
        headings = [p for p in paragraphs if p.get('heading')]
        result['heading_count'] = len(headings)
        selected = headings[:8] + headings[max(8, len(headings) - 4):]
        result['headings'] = [excerpt(p) for p in selected]
        result['headings_omitted'] = max(0, len(headings) - len(selected))
        if args.query:
            indices = [i for i, p in enumerate(paragraphs) if re.search(re.escape(args.query), p['text'], re.I)]
            chosen = indices[:match_budget[0]]
            match_budget[0] -= len(chosen)
            result['matching_paragraph_count'] = len(indices)
            result['matches_omitted'] = len(indices) - len(chosen)
            result['matches'] = [{'match': excerpt(paragraphs[i], args.query),
                                  'context': [dict(excerpt(paragraphs[j], args.query), is_match=j == i) for j in range(max(0, i - args.context), min(len(paragraphs), i + args.context + 1))]}
                                 for i in chosen]
    except (ValueError, KeyError, OSError, ET.ParseError, zipfile.BadZipFile, RuntimeError, NotImplementedError) as error:
        result['error'] = clip(str(error))
    return result


def bounded_int(low, high):
    def parse(value):
        number = int(value)
        if not low <= number <= high:
            raise argparse.ArgumentTypeError(f'must be between {low} and {high}')
        return number
    return parse


def main():
    parser = argparse.ArgumentParser(description=__doc__, epilog=(
        'Never extracts, writes, fetches URLs, or changes books/catalogs. Package checks are not full '
        'OOXML/EPUB conformance or visual checks. Metadata can be wrong: verify publisher front matter '
        'and actual content. Paragraph indices are navigation locators, not printed pages. DOCX body '
        'tables, footnotes and endnotes are included; headers and footers are omitted. EPUB text follows '
        'spine order; non-spine content and image text are not searched. Output excerpts are shortened. '
        'ZIPs are limited to 10,000 members and 512 MiB expanded size. Archive member order is lexical; '
        'confirm split reading order from actual content. Use --offset or --member to inspect omitted parts.'))
    parser.add_argument('path', type=Path, help='DOCX, EPUB, or outer ZIP containing DOCX/EPUB members')
    parser.add_argument('--member', help='Inspect one exact member of an outer ZIP')
    parser.add_argument('--offset', type=bounded_int(0, 10000), default=0, help='Skip this many eligible outer ZIP members')
    parser.add_argument('--max-books', type=bounded_int(1, 20), default=4, help='Maximum packages to inspect (default: 4)')
    parser.add_argument('--query', help='Literal case-insensitive paragraph search, across the selected packages')
    parser.add_argument('--max-matches', type=bounded_int(1, 50), default=8, help='Maximum matched paragraphs across all selected packages (default: 8)')
    parser.add_argument('--context', type=bounded_int(0, 3), default=1, help='Surrounding paragraphs per match (default: 1; maximum: 3)')
    args = parser.parse_args()
    result = {'source_path': str(args.path.expanduser().absolute()), 'read_only': True,
              'locator_note': 'Paragraph indices are not printed pages; fragments are actual EPUB IDs or DOCX bookmarks.'}
    try:
        path = args.path.expanduser()
        require(path.stat().st_size <= MAX_BYTES, 'Input-size limit exceeded')
        raw = path.read_bytes()
        result.update(identity(raw))
        match_budget = [args.max_matches]
        with checked_zip(raw) as archive:
            direct = 'word/document.xml' in archive.namelist() or 'META-INF/container.xml' in archive.namelist()
            if direct:
                require(args.member is None and args.offset == 0, '--member/--offset require an outer ZIP')
                packages = [(None, raw)]
            else:
                members = sorted(n for n in archive.namelist() if n.lower().endswith(('.docx', '.epub')))
                require(members, 'ZIP contains no DOCX or EPUB members')
                require(args.member is None or args.member in members, 'Requested member not found')
                selected = [args.member] if args.member else members[args.offset:args.offset + args.max_books]
                require(selected, 'No packages at this offset')
                result.update(archive_valid=True, eligible_member_count=len(members), members=members[:100],
                              member_names_omitted=max(0, len(members) - 100),
                              selected_members=selected, uninspected_package_count=len(members) - len(selected))
                packages = [(n, archive.read(n)) for n in selected]
        result['books'] = [inspect_package(data, {'source_member': member} if member else {}, args, match_budget) for member, data in packages]
        result['all_selected_packages_valid'] = all(b['package_valid'] for b in result['books'])
        if args.query:
            result['query'] = clip(args.query)
    except (ValueError, KeyError, OSError, ET.ParseError, zipfile.BadZipFile, RuntimeError, NotImplementedError) as error:
        result['error'] = clip(str(error))
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if len(rendered.encode('utf-8')) > MAX_OUTPUT_BYTES:
        # A final cap also covers unusually long IDs, member names, or many OPF renditions.
        result['output_truncated'] = True
        result['output_note'] = 'Detailed output exceeded 256 KiB. Inspect fewer packages with --member or --max-books 1.'
        for key in ('members', 'selected_members'):
            result.pop(key, None)
        keep = {'source_member', 'bytes', 'sha256', 'format', 'package_valid', 'error',
                'paragraph_count', 'text_characters', 'has_text', 'matching_paragraph_count', 'matches_omitted'}
        result['books'] = [{k: v for k, v in b.items() if k in keep} for b in result.get('books', [])]
        rendered = json.dumps(result, ensure_ascii=False, indent=2)
    print(rendered)
    return 0 if result.get('all_selected_packages_valid') else 1


if __name__ == '__main__':
    sys.exit(main())
