"""Exact source selections and citations whose extent is independent of chunks.

Selections are durable source coordinates, never a quotation-string search.
The citation adapter reuses the established Chicago renderer with an isolated
context containing only the selected source blocks. In particular, citing a
unit does not borrow the first search passage's corrections or page locator.
"""
from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
from pathlib import Path

from . import citations
from .local_server import local_base_url
from .storage import append_jsonl, digest, jsonl, now, stable, writer

MAX_SELECTION_BLOCKS = 2000
MAX_SELECTION_CHARS = 200000


def _hash(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _load_unit(lib, unit_id):
    with lib._db() as db:
        row = db.execute('SELECT * FROM reading_units WHERE id=?', (unit_id,)).fetchone()
        if row is None:
            raise ValueError('Reading unit is unavailable; inspect the current book contents.')
        unit = {**json.loads(row['data']), **{k: row[k] for k in ('id', 'work_id', 'node_id', 'title', 'ordinal')}}
        work_row = db.execute('SELECT data FROM works WHERE id=?', (unit['work_id'],)).fetchone()
        work = json.loads(work_row['data'])
        rows = db.execute('''SELECT b.*, ub.role AS unit_role FROM unit_blocks ub
            JOIN blocks b ON b.id=ub.block_id WHERE ub.unit_id=?
            ORDER BY CASE ub.role WHEN 'note' THEN 1 ELSE 0 END, ub.ordinal, b.id''', (unit_id,)).fetchall()
        blocks = []
        for row in rows:
            block = json.loads(row['data'])
            if block.get('is_boilerplate') or block.get('kind') == 'pagebreak' or not block.get('text', '').strip():
                continue
            block.update(id=row['id'], section_id=row['section_id'], global_ordinal=row['ordinal'], unit_role=row['unit_role'])
            blocks.append(block)
        sections = {r['id']: json.loads(r['data']) for r in db.execute('SELECT id,data FROM sections WHERE work_id=?', (unit['work_id'],))}
    if not blocks:
        raise ValueError('This reading unit has no selectable source text.')
    return unit, work, blocks, sections


def _verify_files(lib, work, blocks, expected=None):
    """Check the published generation, live catalog, and actual source bytes."""
    cat = lib._catalog()
    indexed = {f['id']: f for f in work.get('files', [])}
    file_ids = list(dict.fromkeys(b['file_id'] for b in blocks))
    versions = []
    for fid in file_ids:
        file = cat.get('files', {}).get(fid)
        old = indexed.get(fid)
        if not file or not old or not file.get('available') or file.get('state') != 'ready' or file.get('sha256') != old.get('sha256'):
            raise ValueError('Source version is unavailable or changed; synchronize and review the selection.')
        if expected is not None and expected.get(fid) != file.get('sha256'):
            raise ValueError('The saved selection belongs to a different source version; it has not been reattached.')
        try:
            unchanged = digest(Path(file['path'])) == file.get('sha256')
        except OSError:
            unchanged = False
        if not unchanged:
            raise ValueError('Source file changed or disappeared; synchronize before using this text.')
        versions.append({'file_id': fid, 'sha256': file['sha256'], 'path': file['path']})
    return versions


def _ranges(blocks, source_ranges):
    if not isinstance(source_ranges, list) or not 1 <= len(source_ranges) <= MAX_SELECTION_BLOCKS:
        raise ValueError(f'Select between 1 and {MAX_SELECTION_BLOCKS} source blocks.')
    positions = {b['id']: i for i, b in enumerate(blocks)}
    cleaned = []
    for value in source_ranges:
        if not isinstance(value, dict) or set(value) != {'block_id', 'start', 'end'}:
            raise ValueError('Each selection range needs block_id, start, and end.')
        if not isinstance(value['block_id'], str):
            raise ValueError('Selection block IDs must be source identifiers.')
        pos = positions.get(value['block_id'])
        start, end = value['start'], value['end']
        if pos is None or type(start) is not int or type(end) is not int:
            raise ValueError('Selection endpoints must be source blocks in this unit with integer character offsets.')
        # Native browser selections may be made backwards; range offsets remain
        # ordered within each block, and the outer list can be reversed safely.
        if start > end:
            start, end = end, start
        if not 0 <= start < end <= len(blocks[pos]['text']):
            raise ValueError('Selection character offsets are outside the source text.')
        cleaned.append({'block_id': value['block_id'], 'start': start, 'end': end})
    indexes = [positions[r['block_id']] for r in cleaned]
    if len(set(indexes)) != len(indexes):
        raise ValueError('A source block may appear only once in a selection.')
    if indexes == sorted(indexes, reverse=True):
        cleaned.reverse(); indexes.reverse()
    if indexes != list(range(indexes[0], indexes[-1] + 1)):
        raise ValueError('Select one contiguous span; source paragraphs between the endpoints cannot be skipped.')
    for i, item in enumerate(cleaned):
        text = blocks[positions[item['block_id']]]['text']
        if (i and item['start'] != 0) or (i < len(cleaned) - 1 and item['end'] != len(text)):
            raise ValueError('Only the first and last selected source blocks may be partial.')
    if sum(r['end'] - r['start'] for r in cleaned) > MAX_SELECTION_CHARS:
        raise ValueError('The selection is too long; cite the complete reading unit instead.')
    chosen = []
    for value in cleaned:
        block = copy.deepcopy(blocks[positions[value['block_id']]])
        block['text'] = block['text'][value['start']:value['end']]
        chosen.append(block)
    return cleaned, chosen


def _selection_links(lib, unit_id, selection_id):
    base = local_base_url(lib)
    return {'local_unit': base + '/units/' + unit_id,
            'local_selection': base + '/units/' + unit_id + '?selection=' + selection_id,
            'local_preview': base + '/selections/' + selection_id,
            'local_citation': base + '/cite/selection/' + selection_id}


def create_selection(lib, unit_id, source_ranges):
    """Persist an explicitly selected, validated source extent; no usage event."""
    with writer(lib.state):
        unit, work, blocks, _ = _load_unit(lib, unit_id)
        ranges, chosen = _ranges(blocks, source_ranges)
        files = _verify_files(lib, work, chosen)
        lookup = {b['id']: b for b in blocks}
        identity = {'work_id': work['id'], 'unit_id': unit_id, 'source_ranges': ranges,
                    'source_hashes': {f['file_id']: f['sha256'] for f in files}}
        selection_id = stable('selection', json.dumps(identity, sort_keys=True, ensure_ascii=False))
        existing = next((r for r in jsonl(lib.state / 'selections.jsonl') if r['id'] == selection_id), None)
        if existing:
            checked = selection(lib, selection_id)
            if not checked['available']:
                raise ValueError(checked['error'])
            return checked
        record = {'id': selection_id, 'target_scope': 'selection', 'unit_id': unit_id,
                  'work_id': work['id'], 'title': unit['title'], 'work_title': work['title'],
                  'source_ranges': ranges, 'quotation': '\n\n'.join(b['text'] for b in chosen),
                  'source_files': files, 'source_identity': identity,
                  'source_anchors': [{'block_id': r['block_id'], 'locator': lookup[r['block_id']]['locator'],
                                      'text_sha256': _hash(lookup[r['block_id']]['text'])} for r in ranges],
                  'created_at': now(), 'offset_unit': 'unicode_code_points'}
        append_jsonl(lib.state / 'selections.jsonl', record)
        return {**record, 'available': True, 'links': _selection_links(lib, unit_id, selection_id)}


def selection(lib, selection_id):
    record = next((r for r in jsonl(lib.state / 'selections.jsonl') if r['id'] == selection_id), None)
    if record is None:
        raise ValueError('Unknown saved selection.')
    result = copy.deepcopy(record)
    try:
        unit, work, blocks, _ = _load_unit(lib, record['unit_id'])
        ranges, chosen = _ranges(blocks, record['source_ranges'])
        files = _verify_files(lib, work, chosen, record['source_identity']['source_hashes'])
        lookup = {b['id']: b for b in blocks}
        if any(_hash(lookup[a['block_id']]['text']) != a['text_sha256'] or lookup[a['block_id']]['locator'] != a['locator']
               for a in record['source_anchors']):
            raise ValueError('The selection’s source anchors changed; its saved text has not been reattached.')
        if '\n\n'.join(b['text'] for b in chosen) != record['quotation']:
            raise ValueError('Saved selection text no longer matches its exact source coordinates.')
        result.update(available=True, source_files=files)
    except ValueError as error:
        result.update(available=False, error=str(error))
    result['links'] = _selection_links(lib, record['unit_id'], selection_id)
    return result


class _CitationContext:
    """Minimal read-only adapter to the existing citation formatter.

    The private SQLite database contains only the actual chosen blocks, with
    temporary sequential ordinals. No source or published index is modified.
    """
    def __init__(self, lib, work, section, blocks, passage_id, edits, attribution=None):
        self.lib = lib
        self.edits = edits
        self.work = work
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''CREATE TABLE passages(id,work_id,section_id,first_ordinal,last_ordinal,data);
            CREATE TABLE sections(id,data); CREATE TABLE blocks(work_id,ordinal,data);''')
        files = list(dict.fromkeys(b['file_id'] for b in blocks))
        self.db.execute('INSERT INTO passages VALUES(?,?,?,?,?,?)',
                        (passage_id, work['id'], section['id'], 0, len(blocks)-1, json.dumps({'file_ids': files})))
        self.db.execute('INSERT INTO sections VALUES(?,?)', (section['id'], json.dumps(section, ensure_ascii=False)))
        self.db.executemany('INSERT INTO blocks VALUES(?,?,?)',
                            ((work['id'], i, json.dumps(b, ensure_ascii=False)) for i, b in enumerate(blocks)))
        self.passage = {'id': passage_id, 'work_id': work['id'], 'attribution': attribution or section.get('attribution', ''), 'limitations': []}

    def __getattr__(self, name):
        return getattr(self.lib, name)

    def _db(self):
        return self.db

    def _effective(self, cat):
        works, _ = self.lib._effective(cat)
        return works, self.edits

    def read(self, passage_id, **kwargs):
        return {'passage': self.passage}


def _render_extent(lib, work, section, blocks, edits, *, passage_id=None, component=None, locator=None):
    fake_id = passage_id or stable('extent', section['id'], *(b['id'] for b in blocks))
    context = _CitationContext(lib, work, section, blocks, fake_id, edits)
    # A source-marked pinpoint takes priority over a broader inherited section
    # locator for selected prose. Scripture still needs its canonical reference.
    event, bibliography = citations._annotation(edits, section['id'], section.get('source_bibliography'))
    if passage_id and edits.get((passage_id, 'bibliography')):
        event, bibliography = citations._annotation(edits, passage_id, event)
    if component:
        bibliography = component['bibliography']
    resolved = None
    if locator is None and bibliography.get('type') != 'scripture':
        candidate = citations._locator(lib, {}, [{'data': json.dumps(b)} for b in blocks], section, None, [])
        if candidate['origin'] == 'source_page_markers':
            # Verified endnotes may be far from the body. Express disjoint
            # printed pages as disjoint ranges, never a misleading envelope.
            pages = list(dict.fromkeys(str(b['locator']['page']) for b in blocks
                         if Path(b.get('path', '')).suffix.lower() == '.epub' and b.get('locator', {}).get('page')))
            if pages and all(p.isdecimal() for p in pages) and [int(p) for p in pages] == sorted(int(p) for p in pages):
                runs = []
                for page in pages:
                    if runs and int(page) == int(runs[-1][-1]) + 1:
                        runs[-1].append(page)
                    else:
                        runs.append([page])
                value = ', '.join(run[0] if len(run) == 1 else run[0] + '–' + run[-1] for run in runs)
                if len(value) <= 500:
                    candidate.update(value=value, display=value, source_labels=pages)
            resolved = candidate
            locator = {k: candidate[k] for k in ('type', 'value', 'verified', 'evidence')}
    try:
        result = citations._cite_passage(context, fake_id, locator, _segment=component)
    finally:
        context.db.close()
    if resolved:
        result['locator'] = resolved
        result['metadata']['locator'] = resolved
        result['review_fields'] = [f for f in result['review_fields'] if f != 'locator.coverage']
        result['warnings'] = [w for w in result['warnings'] if '2,000 source blocks' not in w and 'source-block inspection limit' not in w]
        result.update(ready=not(result['missing_fields'] or result['review_fields']), needs_review=bool(result['missing_fields'] or result['review_fields']))
    if component:
        result.update(metadata_scope='segment', segment_id=component['segment_id'], text_type=component['text_type'])
        if component['text_type'] == 'unknown' or 'unverified' in component['attribution'].lower():
            _review(result, 'component.attribution', 'This selected component still has unresolved source type or contributor credit.')
    elif not passage_id:
        result['metadata_scope'] = 'section'
    result['source_identity'].pop('passage_id', None)
    if passage_id:
        result['source_identity']['passage_id'] = passage_id
    return result


def _review(result, field, warning):
    result['review_fields'] = list(dict.fromkeys([*result['review_fields'], field]))
    result['warnings'] = list(dict.fromkeys([*result['warnings'], warning]))
    result.update(ready=False, needs_review=True)


def _decorate(lib, result, unit, scope, target_id, blocks, ranges=None, quotation=None):
    result.update(target_scope=scope, target_id=target_id, unit_id=unit['id'])
    result['source_identity'].update(target_scope=scope, target_id=target_id, unit_id=unit['id'],
                                      source_block_ids=[b['id'] for b in blocks])
    if ranges is not None:
        result.update(source_ranges=ranges, quotation=quotation)
        result['source_identity']['source_ranges'] = ranges
    result['citation_id'] = stable('citation', json.dumps(result['source_identity'], ensure_ascii=False, sort_keys=True))
    base = local_base_url(lib)
    result['links'].update(local_unit=base + '/units/' + unit['id'],
                           local_passage=base + '/units/' + unit['id'] + ('?selection=' + target_id if scope == 'selection' else ''),
                           local_citation=base + '/cite/' + scope + '/' + target_id)
    return result


def _credit_groups(lib, unit, blocks, sections, edits):
    """Resolve component/passages live, while leaving unit metadata untouched."""
    from .passage_segments import segments_for_passage, segment_conflict
    from .passage_curation import passage_credit
    with lib._db() as db:
        passages = [dict(r) for r in db.execute('SELECT * FROM passages WHERE work_id=? ORDER BY ordinal', (unit['work_id'],))]
        block_passage = {}
        for block in blocks:
            block_passage[block['id']] = next((p for p in passages if p['section_id'] == block['section_id'] and p['first_ordinal'] <= block['global_ordinal'] <= p['last_ordinal']), None)
        components = {}; conflicts = {}
        for passage in {p['id']: p for p in block_passage.values() if p}.values():
            conflict = segment_conflict(passage['id'], edits)
            if conflict:
                conflicts[passage['id']] = conflict
            if not edits.get((passage['id'], 'segments')) or conflict:
                continue
            rows = db.execute('SELECT data FROM blocks WHERE work_id=? AND ordinal BETWEEN ? AND ? ORDER BY ordinal',
                              (unit['work_id'], passage['first_ordinal'], passage['last_ordinal'])).fetchall()
            for segment in segments_for_passage(passage['id'], edits, rows):
                for block in segment['blocks']:
                    components[block['id']] = segment
    root = sections[unit['root_section_id']]
    groups = []
    for block in blocks:
        passage = block_passage[block['id']]
        pid = passage['id'] if passage else None
        component = components.get(block['id'])
        section = sections[block['section_id']]
        has_section_credit = section.get('source_bibliography') or edits.get((section['id'], 'bibliography')) or edits.get((section['id'], 'attribution'))
        if not has_section_credit:
            section = root
        has_passage_credit = pid and (edits.get((pid, 'bibliography')) or passage_credit(pid, edits) or edits.get((pid, 'segments')))
        key = ('component', pid, component['segment_id']) if component else ('passage', pid) if has_passage_credit else ('section', section['id'])
        if not groups or groups[-1]['key'] != key:
            groups.append({'key': key, 'section': section, 'passage_id': pid if has_passage_credit or component else None,
                           'component': copy.deepcopy(component), 'blocks': [], 'conflict': conflicts.get(pid)})
        groups[-1]['blocks'].append(block)
    return groups


def _mixed_result(components):
    result = copy.deepcopy(components[0])
    result.update(full_note='', short_note='', bibliography='',
                  html={'full_note': '', 'short_note': '', 'bibliography': ''},
                  markdown={'full_note': '', 'short_note': '', 'bibliography': ''},
                  ready=False, needs_review=True, metadata_scope='mixed',
                  metadata={'type': 'mixed', 'authors': [], 'editors': [], 'translators': []},
                  attribution='Separately credited source components', component_citations=components,
                  missing_fields=[], review_fields=['multiple_source_components'], bibliography_required=False,
                  locator={'type': None, 'value': None, 'display': '', 'verified': False},
                  warnings=['The selected text crosses distinct citation scopes. Use the component citations; no single author or locator has been inferred for the combined text.'])
    for key in ('segment_id', 'text_type', 'contribution_target_id'):
        result.pop(key, None)
    for key in ('segment_id', 'passage_id'):
        result['source_identity'].pop(key, None)
    return result


def cite_selection(lib, selection_id, locator=None):
    saved = selection(lib, selection_id)
    if not saved['available']:
        raise ValueError(saved['error'])
    unit, work, blocks, sections = _load_unit(lib, saved['unit_id'])
    ranges, chosen = _ranges(blocks, saved['source_ranges'])
    _, edits = lib._effective(lib._catalog())
    groups = _credit_groups(lib, unit, chosen, sections, edits)
    if len(groups) > 1 and locator is not None:
        raise ValueError('A single locator override cannot cover separately credited selection components.')
    components = []
    for group in groups:
        component = group['component']
        if component:
            component['blocks'] = group['blocks']
        result = _render_extent(lib, work, group['section'], group['blocks'], edits,
                                passage_id=group['passage_id'], component=component, locator=locator)
        if group['conflict']:
            _review(result, 'component.user_correction', group['conflict'])
        selected_ids = {b['id'] for b in group['blocks']}
        result.update(excerpt='\n\n'.join(b['text'] for b in group['blocks']), text_type=result.get('text_type', 'prose'))
        _decorate(lib, result, unit, 'selection', selection_id, group['blocks'],
                  [r for r in ranges if r['block_id'] in selected_ids], result['excerpt'])
        components.append(result)
    result = components[0] if len(components) == 1 else _mixed_result(components)
    return _decorate(lib, result, unit, 'selection', selection_id, chosen, ranges, saved['quotation'])


def cite_unit(lib, unit_id, locator=None):
    unit, work, blocks, sections = _load_unit(lib, unit_id)
    _verify_files(lib, work, blocks)
    _, edits = lib._effective(lib._catalog())
    section = copy.deepcopy(sections[unit['root_section_id']])
    result = _render_extent(lib, work, section, blocks, edits, locator=locator)
    if unit.get('structure_status') != 'supported':
        _review(result, 'unit.boundaries', 'The reading unit’s complete boundaries require review; its source text remains available.')
    # Publication metadata can honestly cite the enclosing volume, but must not
    # masquerade as a recovered essay's independently verified bibliography.
    if result['metadata']['type'] == 'book' and any(c.get('role') == 'editor' for c in work.get('contributors', [])):
        result['citation_extent'] = 'containing_work'
        _review(result, 'unit.bibliography', 'This is a containing-volume citation. The complete unit has no independently verified contribution bibliography; a passage-specific credit does not establish it.')
    return _decorate(lib, result, unit, 'unit', unit_id, blocks)


def record_target_usage(lib, scope, target_id, event):
    """Resolve scope server-side; client text cannot choose a source or author."""
    if scope not in {'unit', 'selection'} or not isinstance(event, dict):
        raise ValueError('Choose a reading unit or saved selection as the research target.')
    if scope == 'selection':
        saved = selection(lib, target_id)
        if not saved['available']:
            raise ValueError(saved['error'])
        unit, work, blocks, _ = _load_unit(lib, saved['unit_id'])
        _, chosen = _ranges(blocks, saved['source_ranges'])
        identity = saved['source_identity']
        extra = {'selection_id': target_id, 'source_ranges': saved['source_ranges'], 'quotation': saved['quotation']}
        citation = cite_selection(lib, target_id)
    else:
        unit, work, chosen, _ = _load_unit(lib, target_id)
        files = _verify_files(lib, work, chosen)
        identity = {'work_id': work['id'], 'unit_id': unit['id'], 'source_hashes': {f['file_id']: f['sha256'] for f in files},
                    'source_block_ids': [b['id'] for b in chosen]}
        extra = {}
        citation = cite_unit(lib, target_id)
    allowed = {}
    for key, limit in [('kind', 40), ('purpose', 100), ('project', 1000), ('destination', 1000), ('notes', 20000), ('evidence', 20000)]:
        if key in event:
            if not isinstance(event[key], str) or len(event[key]) > limit:
                raise ValueError('Invalid research event ' + key + '.')
            allowed[key] = event[key]
    allowed.setdefault('evidence', 'User explicitly recorded this ' + scope + ' as ' + allowed.get('kind', '') + ' in the Reading Room.')
    def credit(result):
        if result.get('component_citations'):
            return '; '.join(dict.fromkeys(credit(c) for c in result['component_citations']))
        metadata = result.get('metadata', {})
        if metadata.get('authors'):
            return '; '.join(citations._display(person) for person in metadata['authors'])
        if result.get('citation_extent') == 'containing_work' and metadata.get('editors'):
            return 'Contributor unverified; edited by ' + '; '.join(citations._display(person) for person in metadata['editors'])
        return result.get('attribution', '')
    return lib.record_usage({**allowed, 'target_scope': scope, 'target_id': target_id, 'unit_id': unit['id'],
                             'work_id': work['id'], 'title': work['title'], 'unit_title': unit['title'],
                             'location': citation.get('locator', {}).get('display') or chosen[0].get('location', ''),
                             'attribution': credit(citation),
                             'source_identity': identity, **extra})
