"""Reviewed structure for damaged exports, applied only to the exact source.

This is an index overlay, not an extraction heuristic. Source text, locators,
and ordinals stay intact; a different edition needs its own source review.
Headings establish reading boundaries, never contributor ownership.
"""

from collections import defaultdict


_LUMINOUS_SHA = '2ef814f8eb5f5ca424a64cc949171d686c754b2187c8325e60da34bb0fe985a6'
_FRONT = 'EPUB/A_Book_of_Luminous_Things-1.xhtml'
_BODY = 'EPUB/A_Book_of_Luminous_Things-2.xhtml'

# Reviewed against this EPUB on 2026-11-03: the printed contents on pp. vii–xiii
# and the corresponding standalone body labels. Its electronic TOC has only
# one book-level link. Each row records member, native anchor, exact source
# text, and (where available) the supporting printed-contents paragraph.
_LUMINOUS_HEADINGS = (
    (_FRONT, 'p_00014', 'ACKNOWLEDGMENTS', None),
    (_FRONT, 'p_00018', 'CONTENTS', None),
    (_FRONT, 'p_00229', 'INTRODUCTION', 'p_00019'),
    (_BODY, 'p_000019', 'Epiphany', 'p_00020'),
    (_BODY, 'p_000068', 'Nature', 'p_00026'),
    (_BODY, 'p_000495', 'The Secret of a Thing', 'p_00057'),
    (_BODY, 'p_000705', 'Travel', 'p_00063'),
    (_BODY, 'p_001060', 'Places', 'p_00086'),
    (_BODY, 'p_001384', 'The Moment', 'p_00113'),
    (_BODY, 'p_001745', 'People Among People', 'p_00123'),
    (_BODY, 'p_002115', "Woman's Skin", 'p_00151'),
    (_BODY, 'p_002380', 'Situations', 'p_00172'),
    (_BODY, 'p_002563', 'Nonattachment', 'p_00189'),
    (_BODY, 'p_002882', 'History', 'p_00215'),
    (_BODY, 'p_003049', 'PERMISSIONS', None),
    (_BODY, 'p_003161', 'INDEX OF AUTHORS', 'p_00226'),
    (_BODY, 'p_003241', 'INDEX OF TITLES OR FIRST LINES', 'p_00227'),
)


def apply_reviewed_structure(source_file: dict, extraction: dict) -> None:
    """Restore verified headings in an in-memory extraction before indexing.

    Require all boundaries to match before changing any: partial application
    would silently extend one section over another. Keep extraction caches raw.
    """
    if source_file.get('sha256') != _LUMINOUS_SHA:
        return
    blocks = extraction['blocks']
    anchors = defaultdict(list)
    for index, block in enumerate(blocks):
        locator = block.get('locator', {})
        anchors[(locator.get('member'), locator.get('element_id'))].append(index)
    targets = []
    for member, anchor, title, contents_anchor in _LUMINOUS_HEADINGS:
        matches = anchors[(member, anchor)]
        if len(matches) != 1:
            break
        index = matches[0]
        block = blocks[index]
        if (block['text'] != title or block['kind'] not in {'paragraph', 'heading'}
                or block.get('is_boilerplate') or block.get('supplemental')
                or block.get('locator', {}).get('note_id')
                or (targets and index <= targets[-1][0])):
            break
        targets.append((index, contents_anchor))
    if len(targets) != len(_LUMINOUS_HEADINGS):
        warning = 'Reviewed section boundaries no longer match the extraction; structure requires source review.'
        if warning not in extraction.setdefault('warnings', []):
            extraction['warnings'].append(warning)
        return
    for index, contents_anchor in targets:
        block = blocks[index]
        evidence = {
            'origin': 'reviewed_source_structure', 'status': 'confirmed',
            'source_sha256': _LUMINOUS_SHA, 'reviewed_at': '2026-11-03',
            'source_locator': dict(block['locator']),
            'scope': 'Section boundary only; no contributor or printed-page correction.',
        }
        if contents_anchor:
            evidence['contents_locator'] = {'member': _FRONT, 'element_id': contents_anchor}
            evidence['evidence'] = 'Printed contents entry and corresponding standalone body heading inspected in this exact source.'
        else:
            evidence['evidence'] = 'Standalone source heading and following acknowledgments, contents, or permissions material inspected in this exact source.'
        if block['text'] == 'Epiphany':
            evidence['pagination_note'] = 'Printed contents lists page 1; the export carries page 4 here. Original locator retained.'
        block.update(kind='heading', level=1, heading_evidence=evidence)
    headings = []
    for block in blocks:
        if block.get('is_boilerplate'):
            continue
        if block.get('supplemental') or block.get('locator', {}).get('note_id'):
            headings = []
        if block['kind'] == 'heading':
            level = block.get('level') or 1
            headings = [(n, label) for n, label in headings if n < level]
            headings.append((level, block['text']))
        block['heading_path'] = [label for _, label in headings]
