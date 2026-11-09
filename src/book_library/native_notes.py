"""Associate native source notes with explicit references, never proximity.

This operates on normalized extraction blocks before sections and passages are
built. Keys are source identities (file ID and extraction ordinal), so identical
note labels in different members/files do not collide. Ambiguous or unreferenced
notes deliberately retain no owner.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy


def _key(file, block):
    return f"{file['id']}:{block['ordinal']}"


def _source(file, block):
    return {'file_id': file['id'], 'sha256': file.get('sha256'),
            'ordinal': block['ordinal'], 'locator': deepcopy(block.get('locator', {}))}


def _anchors(block):
    loc = block.get('locator', {})
    anchors = []
    for key in ('note_id', 'element_id', 'bookmark'):
        value = loc.get(key)
        anchors.extend(value if isinstance(value, list) else [value])
    anchors.extend(block.get('bookmarks', []))
    return {str(value) for value in anchors if value is not None and str(value)}


def analyze_native_notes(work, files, extractions):
    """Return all native notes, with ownership only from unambiguous noterefs.

    Multiple paragraphs sharing one native note ID form one target. A note
    referenced by more than one section stays unassigned: that evidence does
    not authorize attributing its prose to either contribution.
    """
    targets = defaultdict(list)
    notes = {}
    entries = []
    owner = 'front:' + work['id']
    for file in files:
        blocks = extractions.get(file['id'], {}).get('blocks', [])
        readable = [b for b in blocks if b.get('text', '').strip() and not b.get('is_boilerplate') and not b.get('is_navigation')]
        if not file.get('available', True) or file.get('state', 'ready') != 'ready' or not readable:
            owner = None
            continue
        for block in blocks:
            note = block.get('kind') == 'note' or block.get('locator', {}).get('note_id') is not None
            if note:
                key = _key(file, block)
                notes[key] = {'owner': None, 'status': 'unresolved', 'origin': 'native_note_reference',
                              'source': _source(file, block), 'references': []}
                for anchor in _anchors(block):
                    targets[(file['id'], block.get('locator', {}).get('member'), anchor)].append(key)
                continue
            if block.get('is_boilerplate') or block.get('is_navigation'):
                continue
            if block.get('kind') == 'heading' and block.get('text', '').strip():
                owner = _key(file, block)
            entries.append((file, block, owner))
    references = defaultdict(list)
    for file, block, owner in entries:
        for ref in block.get('note_refs', []):
            target = ref.get('target') or {}
            # External package references require a separately verified resolver;
            # a matching basename or note number alone is not enough.
            if target.get('external_href'):
                continue
            anchor = target.get('note_id') or target.get('element_id') or target.get('bookmark')
            if anchor is None or not isinstance(anchor, (str, int)):
                continue
            member = target.get('member') or block.get('locator', {}).get('member')
            keys = targets.get((file['id'], member, str(anchor)), [])
            for key in keys:
                evidence = {'owner': owner, 'source': _source(file, block),
                            'target': deepcopy(target), 'label': ref.get('label') or ref.get('id')}
                if evidence not in references[key]:
                    references[key].append(evidence)
    for key, note in notes.items():
        refs = references[key]
        owners = {ref['owner'] for ref in refs}
        note['references'] = refs
        if len(owners) == 1 and None not in owners:
            note.update(owner=next(iter(owners)), status='confirmed',
                        evidence='Explicit native note references identify one source section; note text is retained in source order.')
        elif len(owners) > 1:
            note['reason'] = 'Native note references span multiple source sections; ownership remains unassigned.'
        elif refs:
            note['reason'] = 'A source gap interrupts the referencing section; note ownership remains unassigned.'
        else:
            note['reason'] = 'No unambiguous native reference identifies this note’s source section.'
    return notes
