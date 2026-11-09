"""Evidence-backed text types and credits inside an immutable passage.

Segments describe existing source blocks; they never rewrite or repartition text.
All nonblank blocks must be accounted for, so a partial credit cannot silently
become an assertion about a whole mixed passage. Endpoints must be nonblank
blocks retained in passage text; blank-only gaps between spans are permitted.
"""
from __future__ import annotations

import json

TEXT_TYPES = ('scripture', 'commentary', 'poetry', 'quotation', 'caption',
              'translation_note', 'editorial', 'index', 'reference', 'prose',
              'mixed', 'unknown')


def validate_text_type(value):
    if value not in TEXT_TYPES:
        raise ValueError('Choose a supported text type: ' + ', '.join(TEXT_TYPES))


def _blocks(rows):
    return [json.loads(row['data']) if 'data' in row.keys() else dict(row) for row in rows]


def validate_segments(value, rows):
    from .citations import validate_bibliography
    if not isinstance(value, list) or not 1 <= len(value) <= 100:
        raise ValueError('Segments must be a list of 1–100 source spans.')
    if len(json.dumps(value, ensure_ascii=False)) > 200000:
        raise ValueError('Segment metadata exceeds the 200,000-character limit.')
    blocks = _blocks(rows)
    positions = {block['id']: i for i, block in enumerate(blocks)}
    covered = set(); previous = -1
    for segment in value:
        allowed = {'first_block_id', 'last_block_id', 'text_type', 'attribution', 'bibliography', 'notes'}
        if not isinstance(segment, dict) or set(segment) - allowed:
            raise ValueError('Segments require source block boundaries, text_type, attribution, bibliography, and optional notes.')
        first = positions.get(segment.get('first_block_id')); last = positions.get(segment.get('last_block_id'))
        if first is None or last is None or first > last or first <= previous:
            raise ValueError('Segment boundaries must be ordered, nonoverlapping blocks within this passage.')
        if not blocks[first].get('text', '').strip() or not blocks[last].get('text', '').strip():
            raise ValueError('Segment endpoints must be nonblank source blocks retained in the passage text; move the boundary past blank paragraphs.')
        validate_text_type(segment.get('text_type'))
        if segment['text_type'] == 'mixed':
            raise ValueError('Split mixed material into individually described segments, or leave it unknown.')
        if not isinstance(segment.get('attribution'), str) or not segment['attribution'].strip() or len(segment['attribution']) > 2000:
            raise ValueError('Each segment requires a bounded display credit.')
        validate_bibliography(segment.get('bibliography'))
        if 'notes' in segment and (not isinstance(segment['notes'], str) or len(segment['notes']) > 4000):
            raise ValueError('Segment notes must be text of at most 4,000 characters.')
        if segment['text_type'] == 'scripture' and segment['bibliography'].get('type') != 'scripture':
            raise ValueError('Scripture segments require Scripture citation metadata.')
        if segment['text_type'] != 'scripture' and segment['bibliography'].get('type') == 'scripture':
            raise ValueError('Scripture citation metadata belongs only to Scripture segments, not commentary or other text types.')
        covered.update(range(first, last + 1)); previous = last
    if any(i not in covered and block.get('text', '').strip() for i, block in enumerate(blocks)):
        raise ValueError('Segments must account for every nonblank source block in the passage.')


def segments_for_passage(passage_id, edits, block_rows):
    event = edits.get((passage_id, 'segments'))
    if not event or segment_conflict(passage_id, edits):
        return []
    blocks = _blocks(block_rows)
    validate_segments(event['value'], blocks)
    positions = {block['id']: i for i, block in enumerate(blocks)}
    return [{**segment, 'segment_id': segment['first_block_id'], 'event': event,
             'blocks': blocks[positions[segment['first_block_id']]:positions[segment['last_block_id']] + 1]}
            for segment in event['value']]


def segment_conflict(passage_id, edits):
    """Automatic spans cannot silently supersede the user's scoped correction."""
    event = edits.get((passage_id, 'segments'))
    if not event or event.get('origin') == 'user':
        return None
    user_fields = [field for field in ('attribution', 'text_type')
                   if edits.get((passage_id, field), {}).get('origin') == 'user']
    bibliography = edits.get((passage_id, 'bibliography'), {})
    for field in ('authors', 'type'):
        if field in bibliography.get('value', {}) and bibliography.get('field_events', {}).get(field, bibliography).get('origin') == 'user':
            user_fields.append('bibliography.' + field)
    if user_fields:
        return ('Automatic component credits are withheld because this passage has a user correction to '
                + ', '.join(user_fields) + '. Recheck the component boundaries and save user-approved segments before using component citations.')
    return None


def segment_summary(segments):
    labels = list(dict.fromkeys(segment['text_type'] for segment in segments))
    credits = list(dict.fromkeys(segment['text_type'].replace('_', ' ').capitalize() + ': ' + segment['attribution'] for segment in segments))
    return {'text_type': labels[0] if len(labels) == 1 else 'mixed',
            'text_types': labels, 'attribution': '; '.join(credits),
            'segments': [{key: value for key, value in segment.items() if key not in ('blocks', 'event', 'bibliography')}
                         for segment in segments]}
