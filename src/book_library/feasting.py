"""Recover FOTW essay credits from explicit bylines and the same-volume roster.

This is deliberately a source-specific convention, not generic person-name
guessing. Source blocks and their order are unchanged. Note owners require a
unique reciprocal link to a paragraph in a verified contribution. Consumers
must keep unowned notes separate from the preceding essay's attribution.
"""
from __future__ import annotations

import collections
import json
import re
import unicodedata

PERSPECTIVES = {'Theological Perspective', 'Pastoral Perspective', 'Exegetical Perspective', 'Homiletical Perspective'}
_NUMERIC_LINK = re.compile(r'\d+[.)]?')
_NUMBERED_NOTE = re.compile(r'^\s*\d+\.\s+\S')


def block_key(file_id, ordinal):
    return f'{file_id}:{ordinal}'


def _norm(value):
    return ' '.join(unicodedata.normalize('NFKC', value).split()).casefold()


def _source(entry):
    file, block = entry['file'], entry['block']
    return {'block_key': entry['key'], 'file_id': file['id'], 'path': file.get('path'),
            'sha256': file.get('sha256'), 'ordinal': block['ordinal'],
            'locator': block.get('locator', {}), 'text': block.get('text', '')[:1000]}


def _name_prefix(text):
    """The FOTW roster explicitly separates a full printed name from its role."""
    if ',' not in text:
        return None
    name = text.split(',', 1)[0].strip()
    if not 3 <= len(name) <= 120 or not 2 <= len(name.split()) <= 12:
        return None
    if not all(c.isalpha() or c.isspace() or c in '.-’\'ʻ' for c in name):
        return None
    return name


def _looks_like_trailing_note(block):
    # Source volumes disagree about whether the inline anchor or note anchor
    # ends in 'a'. Never identify note content by an anchor suffix alone.
    if block.get('kind') == 'note' or _NUMBERED_NOTE.match(block.get('text', '')):
        return True
    # B2's superscript note numbers concatenate directly with the first word.
    # The source's numeric backlink and bookmark disambiguate them from headings.
    prefix = re.match(r'^\s*(\d+)', block.get('text', ''))
    return bool(prefix and block.get('bookmarks') and any(
        _NUMERIC_LINK.fullmatch(str(link.get('label', '')).strip()) and
        str(link.get('label', '')).strip().rstrip('.)') == prefix[1] and
        (link.get('target') or {}).get('bookmark')
        for link in block.get('links', [])))


def analyze_feasting(work, file_blocks):
    """Return source-backed contribution and note ownership without mutation.

    ``file_blocks`` is an ordered iterable of ``(file_record, extraction_blocks)``.
    Pass every source part in order, with None blocks for unavailable/failed
    parts. These and textless parts break essay continuity; they do not prevent
    a complete essay elsewhere from using the volume roster or source links.
    Keys use stable file identity plus extraction ordinal. ``contributions`` maps
    each perspective heading key to author, bibliography and source evidence.
    ``owners`` maps body/byline/note block keys to that heading. ``notes`` includes
    recognized but unresolved notes with owner None; never inherit a last essay
    author for one of those. ``boundaries`` marks where trailing shared notes
    start so the indexer can flush the preceding body before changing ownership.
    Editorial/user overrides remain the caller's responsibility.
    """
    empty = {'contributions': {}, 'owners': {}, 'notes': {}, 'boundaries': [], 'stats': {}}
    if not str(work.get('title', '')).startswith('Feasting on the Word'):
        return empty
    ordered_entries = []
    for file, blocks in file_blocks:
        if blocks is None or not any(b.get('text', '').strip() and not b.get('is_boilerplate') for b in blocks):
            ordered_entries.append(None)
            continue
        ordered_entries.extend({'file': file, 'block': b, 'key': block_key(file['id'], b['ordinal'])}
                               for b in blocks)
    entries = [entry for entry in ordered_entries if entry is not None]
    if len({e['key'] for e in entries}) != len(entries):
        raise ValueError('Duplicate source block identity in Feasting preparation.')
    rosters = collections.defaultdict(dict)
    for entry in entries:
        b = entry['block']
        if b.get('is_boilerplate') or b.get('kind') == 'heading':
            continue
        if not any(_norm(str(h)) == 'contributors' for h in b.get('heading_path', [])):
            continue
        name = _name_prefix(b.get('text', ''))
        if name:
            rosters[_norm(name)].setdefault(name, entry)
    roster = {key: next(iter(value.items())) for key, value in rosters.items() if len(value) == 1}

    notes = {}
    for entry in entries:
        b = entry['block']
        if b.get('kind') == 'note':
            notes[entry['key']] = {'owner': None, 'status': 'unresolved', 'source': _source(entry), 'markers': list(b.get('bookmarks', []))}
    sections = []
    current = []
    for entry in ordered_entries:
        if entry is None:
            if current:
                sections.append(current)
            current = []
            continue
        b = entry['block']
        if b.get('kind') == 'heading' and b.get('text', '').strip() and not b.get('is_boilerplate'):
            if current:
                sections.append(current)
            current = [entry]
        elif current:
            current.append(entry)
    if current:
        sections.append(current)

    contributions = {}; owners = {}; boundaries = []
    perspective_count = 0
    for section in sections:
        heading = section[0]; h = heading['block']; title = h.get('text', '').strip()
        if h.get('perspective_kind', title) not in PERSPECTIVES:
            continue
        perspective_count += 1
        candidates = []
        for index, entry in enumerate(section[1:], 1):
            b = entry['block']; text = b.get('text', '').strip()
            if entry['key'] in notes or b.get('is_boilerplate') or b.get('kind') != 'paragraph':
                continue
            if _norm(text) in roster and '\n' not in text and len(text) <= 120:
                candidates.append((index, entry, roster[_norm(text)]))
        if len(candidates) != 1:
            continue
        index, byline, (name, roster_entry) = candidates[0]
        # A name in the middle of an essay is not a closing byline. Require prose
        # before it, and only known notes/blank/boilerplate blocks after it.
        prose = [e for e in section[1:index] if e['key'] not in notes and not e['block'].get('is_boilerplate')]
        if sum(len(e['block'].get('text', '').strip()) for e in prose) < 80:
            continue
        trailing = [e for e in section[index + 1:] if e['block'].get('text', '').strip() and not e['block'].get('is_boilerplate')]
        if any(not _looks_like_trailing_note(e['block']) for e in trailing):
            continue
        for entry in trailing:
            notes[entry['key']] = {'owner': None, 'status': 'unresolved', 'source': _source(entry),
                                   'markers': list(entry['block'].get('bookmarks', []))}
        path = list(h.get('heading_path') or [title])
        if path[-1] != title:
            path.append(title)
        evidence = {'origin': 'source_closing_byline_and_contributor_roster', 'status': 'confirmed',
                    'heading': _source(heading), 'byline': _source(byline), 'roster': _source(roster_entry),
                    'method': 'Standalone closing byline matches the same-volume Contributors roster; source notes are excluded.'}
        locator = {'type': 'section', 'value': ' / '.join(path), 'verified': len(path) > 1,
                   'evidence': 'Source heading hierarchy recorded with the verified contribution byline.'}
        bibliography = {'type': 'chapter', 'title': title, 'authors': [{'literal': name}], 'locator': locator}
        contributions[heading['key']] = {'key': heading['key'], 'author': name, 'heading': title, 'heading_path': path,
                                         'bibliography': bibliography, 'evidence': evidence,
                                         'source_bibliography': {'origin': 'source_byline', 'status': 'confirmed',
                                                                 'evidence': json.dumps(evidence, ensure_ascii=False),
                                                                 'value': bibliography}}
        for entry in section[:index + 1]:
            if entry['key'] not in notes and not entry['block'].get('is_boilerplate'):
                owners[entry['key']] = heading['key']
        if trailing:
            boundaries.append(trailing[0]['key'])

    # Work-wide bookmark lookup permits split Word files, but duplicates remain
    # unresolved instead of guessing which edition/paragraph a link intended.
    bookmarks = collections.defaultdict(list)
    for entry in entries:
        for marker in entry['block'].get('bookmarks', []):
            bookmarks[marker].append(entry)
    for entry in entries:
        key = entry['key']
        if key not in notes:
            continue
        b = entry['block']; destinations = []
        own = set(notes[key]['markers'])
        for link in b.get('links', []):
            if not _NUMERIC_LINK.fullmatch(str(link.get('label', '')).strip()):
                continue
            target = (link.get('target') or {}).get('bookmark')
            possible = bookmarks.get(target, [])
            if len(possible) != 1:
                continue
            body = possible[0]
            reciprocal = [back for back in body['block'].get('links', [])
                          if (back.get('target') or {}).get('bookmark') in own]
            if not reciprocal or body['key'] not in owners:
                continue
            destinations.append((owners[body['key']], body['key'], target))
        unique = {owner for owner, _, _ in destinations}
        if len(unique) == 1:
            owner = unique.pop(); owners[key] = owner
            notes[key].update(owner=owner, status='confirmed',
                              evidence={'method': 'Unique reciprocal source note links identify a paragraph in this verified contribution.',
                                        'targets': [{'block_key': body, 'bookmark': marker} for _, body, marker in destinations]})
    return {'contributions': contributions, 'owners': owners, 'notes': notes, 'boundaries': boundaries,
            'stats': {'perspectives': perspective_count, 'verified_contributions': len(contributions),
                      'roster_names': len(roster), 'source_notes': len(notes),
                      'notes_with_verified_owner': sum(n['owner'] is not None for n in notes.values())}}
