"""Read-only projections of source-backed outline nodes and reading units."""
from __future__ import annotations

import json
from urllib.parse import urlencode


def section(lib, section_id, work_id=None):
    with lib._db() as db:
        row = db.execute('SELECT * FROM sections WHERE id=?', (section_id,)).fetchone()
        if not row or (work_id is not None and row['work_id'] != work_id):
            raise ValueError('That section is not part of this book.')
        data = json.loads(row['data'])
        first = db.execute('SELECT id FROM passages WHERE section_id=? AND boilerplate=0 ORDER BY ordinal LIMIT 1', (section_id,)).fetchone()
    return {**data, 'work_id': row['work_id'], 'passage_id': first[0] if first else None}


def contents(lib, work_id, offset=0, limit=100):
    offset = max(0, int(offset)); limit = max(1, min(500, int(limit)))
    with lib._db() as db:
        row = db.execute('SELECT data FROM works WHERE id=?', (work_id,)).fetchone()
        if not row:
            raise ValueError('Unknown book.')
        work = json.loads(row[0])
        rows = db.execute('SELECT * FROM outline_nodes WHERE work_id=? ORDER BY ordinal,id', (work_id,)).fetchall()
    ordered = [{**json.loads(r['data']), **{k: r[k] for k in ('id', 'title', 'parent_id', 'depth', 'unit_id', 'ordinal')}} for r in rows]
    by_id = {n['id']: n for n in ordered}
    positions = {n['id']: i for i, n in enumerate(ordered)}
    # Prefer complete top-level branches. Oversized branches receive an explicit
    # continuation with ancestors repeated, never an unexplained orphan heading.
    end = min(len(ordered), offset + limit)
    if offset < len(ordered) and end < len(ordered):
        root_starts = [i for i in range(offset + 1, end + 1) if not ordered[i]['parent_id']]
        if root_starts:
            end = root_starts[-1]
        else:
            depth = ordered[offset]['depth']
            boundaries = [i for i in range(offset + 1, end + 1) if ordered[i]['depth'] <= depth + 1]
            if boundaries:
                end = boundaries[-1]
    selected = {n['id'] for n in ordered[offset:end]}
    included = set(selected)
    for ident in list(selected):
        parent = by_id[ident]['parent_id']; seen = set()
        while parent in by_id and parent not in seen:
            seen.add(parent); included.add(parent); parent = by_id[parent]['parent_id']
    projected = {ident: {**by_id[ident], 'children': [], 'continued': ident not in selected,
                         'has_content': bool(by_id[ident]['unit_id'])}
                 for ident in included}
    roots = []
    for ident in sorted(included, key=positions.get):
        node = projected[ident]
        if node['parent_id'] in projected:
            projected[node['parent_id']]['children'].append(node)
        else:
            roots.append(node)
    return {'work': work, 'nodes': roots, 'report': work.get('structure', {}),
            'offset': offset, 'total_nodes': len(ordered), 'next_offset': end if end < len(ordered) else None,
            'previous_offset': max(0, offset-limit) if offset else None}


def _note_links(blocks):
    targets = {}
    for block in blocks:
        loc = block.get('locator', {})
        values = [loc.get('element_id'), loc.get('note_id'), loc.get('bookmark')]
        values.extend(block.get('bookmarks', []))
        for value in values:
            for anchor in value if isinstance(value, list) else [value]:
                if anchor:
                    targets.setdefault((block['file_id'], loc.get('member'), str(anchor)), []).append(block)
    for block in blocks:
        block['note_links'] = []; block['backlinks'] = []
    for block in blocks:
        for ref in block.get('note_refs', []):
            target = ref.get('target') or {}
            anchor = target.get('element_id') or target.get('note_id') or target.get('bookmark')
            matches = targets.get((block['file_id'], target.get('member') or block.get('locator', {}).get('member'), str(anchor)), [])
            matches = [b for b in matches if b.get('role') == 'note' and b['id'] != block['id']]
            # A note can consist of several paragraphs with the same native ID.
            if matches:
                note = matches[0]
                link = {'target_block_id': note['id'], 'label': str(ref.get('label') or ref.get('id') or 'Source note')}
                if link not in block['note_links']:
                    block['note_links'].append(link)
                if block['id'] not in note['backlinks']:
                    note['backlinks'].append(block['id'])
    # Feasting's verified ownership includes the reciprocal anchor mapping even
    # where the generic DOCX extractor has not classified hyperlinks as noterefs.
    for note in blocks:
        ownership = note.get('note_ownership') or {}
        if note.get('role') != 'note' or not ownership.get('owner'):
            continue
        for link in note.get('links', []):
            target = link.get('target') or {}
            anchor = target.get('bookmark') or target.get('element_id')
            if not anchor:
                continue
            matches = targets.get((note['file_id'], target.get('member') or note.get('locator', {}).get('member'), str(anchor)), [])
            for body in matches:
                if body.get('role') == 'note':
                    continue
                label = str(link.get('label') or 'Source note')
                entry = {'target_block_id': note['id'], 'label': label}
                if entry not in body['note_links']:
                    body['note_links'].append(entry)
                if body['id'] not in note['backlinks']:
                    note['backlinks'].append(body['id'])


def _passage_ranges(db, passage, start, end):
    if not 0 <= start < end <= len(passage['text']):
        raise ValueError('Search excerpt coordinates are outside the source passage.')
    rows = db.execute('SELECT id,text,data FROM blocks WHERE work_id=? AND ordinal BETWEEN ? AND ? ORDER BY ordinal', (passage['work_id'], passage['first_ordinal'], passage['last_ordinal'])).fetchall()
    ranges = []; position = 0
    for b in rows:
        if not b['text'].strip():
            continue
        lo, hi = max(0, start-position), min(len(b['text']), end-position)
        if lo < hi and json.loads(b['data']).get('kind') != 'pagebreak':
            ranges.append({'block_id': b['id'], 'start': lo, 'end': hi})
        position += len(b['text'])+2
    return ranges


def read_unit(lib, unit_id, anchor=None, cursor=0, max_chars=200000, match=None, anchor_offset=0):
    cursor = int(cursor); max_chars = max(500, min(500000, int(max_chars)))
    anchor_offset = int(anchor_offset)
    if anchor_offset < 0:
        raise ValueError('Source anchor offset must be nonnegative.')
    if cursor < 0:
        raise ValueError('Reading cursor must be nonnegative.')
    with lib._db() as db:
        row = db.execute('SELECT * FROM reading_units WHERE id=?', (unit_id,)).fetchone()
        if not row:
            raise ValueError('Reading unit unavailable; synchronize or consult source history.')
        unit = {**json.loads(row['data']), **{k: row[k] for k in ('id', 'work_id', 'title', 'node_id', 'ordinal')}}
        work = json.loads(db.execute('SELECT data FROM works WHERE id=?', (unit['work_id'],)).fetchone()[0])
        rows = db.execute("SELECT b.*,ub.role FROM unit_blocks ub JOIN blocks b ON b.id=ub.block_id WHERE ub.unit_id=? ORDER BY CASE ub.role WHEN 'note' THEN 1 ELSE 0 END,ub.ordinal,b.id", (unit_id,)).fetchall()
        members = [{**json.loads(r['data']), 'section_id': r['section_id'], 'role': r['role']} for r in rows]
        raw = [b for b in members if not b.get('is_boilerplate') and b.get('kind') != 'pagebreak' and (b['text'].strip() or b.get('image_refs'))]
        # Outline links can start at a genuine source page marker. Markers are
        # members of the unit but intentionally have no rendered text block.
        # Resolve only this navigation case to the next readable member in the
        # same body/note stream (or the preceding member at its end). Never
        # reinterpret quotation offsets, match ranges, or unrelated anchors.
        marker = next((b for b in members if b['id'] == anchor and b.get('kind') == 'pagebreak'), None)
        if marker and not match and anchor_offset == 0:
            position = next(i for i, b in enumerate(members) if b['id'] == marker['id'])
            readable_ids = {b['id'] for b in raw if b['role'] == marker['role']}
            following = next((b for b in members[position + 1:] if b['id'] in readable_ids), None)
            preceding = next((b for b in reversed(members[:position]) if b['id'] in readable_ids), None)
            destination = following or preceding
            if destination:
                anchor = destination['id']
        file_ids = list(dict.fromkeys(b['file_id'] for b in raw))
        if marker and marker['file_id'] not in file_ids:
            file_ids.append(marker['file_id'])
        if not lib._current_files({'file_ids': file_ids}, work):
            raise ValueError('A source file changed or disappeared; synchronize before reading this unit.')
        passage_rows = db.execute('SELECT id,first_ordinal,last_ordinal FROM passages WHERE work_id=? AND boilerplate=0 ORDER BY first_ordinal', (unit['work_id'],)).fetchall()
        by_block = {}
        by_global = sorted(raw, key=lambda b: b['global_ordinal']); i = 0
        for p in passage_rows:
            while i < len(by_global) and by_global[i]['global_ordinal'] < p['first_ordinal']:
                i += 1
            j = i
            while j < len(by_global) and by_global[j]['global_ordinal'] <= p['last_ordinal']:
                by_block[by_global[j]['id']] = p['id']; j += 1
        nodes = {r['id']: {**json.loads(r['data']), 'id': r['id'], 'title': r['title'], 'parent_id': r['parent_id'], 'depth': r['depth'], 'unit_id': r['unit_id']}
                 for r in db.execute('SELECT * FROM outline_nodes WHERE work_id=?', (unit['work_id'],))}
        ancestors = []; parent = nodes.get(unit['node_id'], {}).get('parent_id'); seen = set()
        while parent in nodes and parent not in seen:
            seen.add(parent); ancestors.append(nodes[parent]); parent = nodes[parent]['parent_id']
        ancestors.reverse()
        def neighbor(direction):
            op, order = ('<', 'DESC') if direction == 'previous' else ('>', 'ASC')
            other = db.execute(f'SELECT id,title,node_id FROM reading_units WHERE work_id=? AND ordinal {op} ? ORDER BY ordinal {order} LIMIT 1', (unit['work_id'], unit['ordinal'])).fetchone()
            if not other:
                return None
            context = nodes.get(nodes.get(other['node_id'], {}).get('parent_id'), {}).get('title')
            return {**dict(other), 'contextual_title': other['title'] + (' · ' + context if context else '')}
        previous, following = neighbor('previous'), neighbor('next')
        source_ranges = []
        if match:
            p = db.execute('SELECT * FROM passages WHERE id=? AND work_id=?', (match.get('passage_id'), unit['work_id'])).fetchone()
            if not p:
                raise ValueError('The matching excerpt is unavailable in this reading unit.')
            source_ranges = _passage_ranges(db, p, int(match.get('start', 0)), int(match['end']) if match.get('end') is not None else len(p['text']))
            available_ids = {b['id'] for b in raw}
            if not source_ranges or any(r['block_id'] not in available_ids for r in source_ranges):
                raise ValueError('The matching excerpt crosses reading-unit boundaries.')
            anchor = source_ranges[0]['block_id']
            anchor_offset = source_ranges[0]['start']
    root_depth = nodes.get(unit['node_id'], {}).get('depth', 1)
    unit['contextual_title'] = unit['title'] + (' · ' + ancestors[-1]['title'] if ancestors else '')
    _note_links(raw)
    total = sum(max(1, len(b['text'])) for b in raw)
    if cursor >= total and cursor:
        raise ValueError('Reading cursor is beyond this unit.')
    if anchor:
        position = 0
        for block_index, b in enumerate(raw):
            if b['id'] == anchor or by_block.get(b['id']) == anchor:
                if anchor_offset > len(b['text']):
                    raise ValueError('Source anchor offset is outside the block.')
                if not cursor and (position + anchor_offset >= max_chars or block_index >= 1500):
                    cursor = position + anchor_offset
                anchor = b['id']; break
            position += max(1, len(b['text']))
        else:
            raise ValueError('Source anchor is not a member of this reading unit.')
    output = []; position = 0; used = 0; next_cursor = None
    for b in raw:
        length = len(b['text']); width = max(1, length)
        start = position; position += width
        if position <= cursor:
            continue
        lo = max(0, cursor-start); available = max_chars-used
        # Keep normal source blocks whole. Only a block larger than the entire
        # page allowance is fragmented, with explicit source offsets.
        if output and (length-lo > available or len(output) >= 1500):
            next_cursor = start; break
        hi = min(length, lo+available)
        fragment = lo > 0 or hi < length
        public = lib._reading_block(b, b['text'][lo:hi], fragment)
        public.update(source_char_start=lo, source_char_end=hi, source_length=length,
                      role=b['role'], passage_id=by_block.get(b['id']),
                      heading_depth=max(2, int(b.get('structure_depth', b.get('level') or root_depth))-root_depth+2),
                      note_links=b['note_links'], backlinks=b['backlinks'])
        output.append(public); used += max(1, hi-lo)
        if hi < length:
            next_cursor = start+hi; break
    limitations = []
    if unit.get('structure_status') == 'needs_review':
        limitations.append('Some structural boundaries need review; this view contains the currently supported source membership.')
    if next_cursor is not None or cursor:
        limitations.append('This is a continuation within the same reading unit; use the continuation links for the remaining text.')
    return {'unit': unit, 'work': work, 'ancestors': ancestors, 'blocks': output,
            'previous': previous, 'next': following, 'cursor': cursor,
            'next_cursor': next_cursor, 'previous_cursor': max(0, cursor-max_chars) if cursor else None,
            'anchor': anchor, 'source_ranges': source_ranges, 'limitations': limitations, 'total_chars': total,
            'source_paths': list(dict.fromkeys(b.get('path') for b in raw if b.get('path')))}


def attach_search_targets(lib, result):
    """Attach source coordinates, not a client-side quotation text search."""
    with lib._db() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='reading_units'").fetchone():
            return result
        for hit in result.get('direct', []) + result.get('connections', []):
            p = db.execute('SELECT * FROM passages WHERE id=?', (hit['id'],)).fetchone()
            if not p:
                continue
            start = max(0, int(hit.get('excerpt_start', hit.get('read_offset', 0))))
            end = min(len(p['text']), int(hit.get('excerpt_end', start+700)))
            ranges = _passage_ranges(db, p, start, end) if start < end else []
            if not ranges:
                continue
            owner = db.execute('SELECT ru.id,ru.data FROM unit_blocks ub JOIN reading_units ru ON ru.id=ub.unit_id WHERE ub.block_id=? ORDER BY ru.ordinal LIMIT 1', (ranges[0]['block_id'],)).fetchone()
            if owner and json.loads(owner['data']).get('structure_status') != 'needs_review':
                hit['unit_id'] = owner['id']; hit['source_ranges'] = ranges
                hit['read_url'] = '/units/'+owner['id']+'?'+urlencode({'anchor': ranges[0]['block_id'], 'match': p['id'], 'start': start, 'end': end})+'#'+ranges[0]['block_id']
            else:
                hit['read_url'] = '/read/'+hit['id']
                hit.setdefault('limitations', []).append('Reading-unit boundaries require review; open this source excerpt for bounded context.')
    return result
