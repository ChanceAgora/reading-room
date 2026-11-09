"""Read-only recommendations over saved review evidence and individual decisions.

The grouping is presentation, not a new metadata scope. Changes still belong to
the current target and keep the existing per-field curation semantics.
"""
from __future__ import annotations

import copy
import hashlib
import json

from .citations import _display
from .review_items import review_items


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':')).encode()).hexdigest()


def display_value(value):
    if value is None or value == '':
        return 'Not recorded'
    if isinstance(value, list):
        return '; '.join(_display(person) if isinstance(person, dict) else str(person) for person in value) if value else 'None explicitly recorded'
    return str(value)


def _education(field):
    from .review_education import field_education
    return {**field_education(field['key'], field.get('label', ''), field.get('help', ''), field.get('example', '')),
            **{key: field[key] for key in ('question', 'purpose', 'effect', 'priority', 'action_label') if field.get(key)}}


def _family(key, fields):
    linked = {key}
    while True:
        expanded = linked | {related for current in linked for related in fields.get(current, {}).get('related_fields', []) if related in fields}
        expanded |= {current for current, field in fields.items() if linked.intersection(field.get('related_fields', []))}
        if expanded == linked:
            return tuple(sorted(linked))
        linked = expanded


def _status(items):
    states = {item['status'] for item in items}
    if 'pending' in states:
        return 'pending'
    if 'accepted' in states:
        return 'accepted'
    if states == {'saved'}:
        return 'saved'
    if 'later' in states:
        return 'later'
    return 'kept' if 'kept' in states else 'rejected'


def _fingerprint(context, recommendation):
    source_map = {source['id']: source for source in context.get('evidence', [])}
    fields = {field['key']: field for field in context['fields']}
    comparison = recommendation.get('comparison') or {}
    comparison_facts = {key: comparison.get(key) for key in ('recorded_isbn', 'compared_isbn', 'relationship')}
    comparison_facts['records'] = sorted(
        ({key: record.get(key) for key in ('isbn', 'title', 'format', 'publisher', 'year', 'edition', 'origin')}
         for record in comparison.get('records', [])), key=lambda record: json.dumps(record, sort_keys=True))
    return _digest({
        'fields': [{key: fields[name].get(key) for key in ('key', 'value', 'raw_value', 'status', 'inherited', 'evidence')}
                   for name in recommendation['fields'] if name in fields],
        'items': sorted((item['id'], item['fingerprint']) for item in recommendation['items']),
        'source': context.get('book_revision') if recommendation['kind'] == 'edition' else context.get('source_fingerprint'),
        'comparison': comparison_facts,
        'facts': sorted(recommendation.get('reported_facts', []), key=lambda fact: json.dumps(fact, sort_keys=True)),
        'evidence': sorted((source.get('source_id', ''), _digest(source_map.get(source.get('source_id'), {}).get('text', '')))
                           for source in recommendation.get('evidence', [])),
    })


def recommendations(context, draft):
    """Project one understandable decision at a time; never persist on GET."""
    fields = {field['key']: field for field in context['fields']}
    target = context['target']
    result, groups = [], {}
    for item in review_items(context, draft):
        if target['scope'] != 'work' and not fields[item['field']].get('editable', True):
            continue
        family = _family(item['field'], fields)
        # An actionable correction and a still-unanswered related question are
        # distinct choices; accepting one must not silently close the other.
        key = ('changes' if item['kind'] == 'suggestion' else 'question', family)
        groups.setdefault(key, []).append(item)
    assessments = [a for a in draft.get('assessments', []) if isinstance(a, dict)]
    expanded_groups = []
    for (kind, family), items in groups.items():
        competing = len({item['field'] for item in items}) != len(items)
        # Alternatives are independent recommendations, not a bundle that
        # silently picks whichever proposed value happens to come last.
        if competing:
            expanded_groups.extend((kind, family, [item], item['id']) for item in items)
        else:
            expanded_groups.append((kind, family, items, None))
    for kind, family, items, alternative_id in expanded_groups:
        represented = list(dict.fromkeys(item['field'] for item in items))
        lead = fields[represented[0]]
        education = _education(lead)
        assessment = next((a for a in assessments if a.get('kind') == 'field'
                           and set(a.get('fields', [])).intersection(represented)
                           and a.get('outcome') == ('change' if kind == 'changes' else 'unresolved')), {})
        reasons = list(dict.fromkeys(reason for item in items for reason in item.get('reasons', [])))
        evidence = []
        for item in items:
            for reference in item.get('evidence', []):
                if reference not in evidence:
                    evidence.append(reference)
        proposal_strengths = [proposal.get('strength', 'likely') for proposal in draft.get('suggestions', [])
                              if proposal.get('field') in represented]
        strength = assessment.get('strength') or ('well_supported' if proposal_strengths and all(s == 'well_supported' for s in proposal_strengths) else 'likely') if kind == 'changes' else assessment.get('strength', 'needs_evidence')
        labels = [fields[name].get('label', name).lower() for name in represented]
        if kind == 'changes':
            values = [display_value(item.get('queued_value', item.get('value'))) for item in items]
            if represented == ['text_type']:
                options = {option['value']: option['label'] for option in lead.get('options', [])}
                values = [options.get(items[0].get('value'), values[0])]
            recommendation = assessment.get('recommendation') or ('Use “' + values[0] + '”.' if len(items) == 1 else 'Update the related ' + ' and '.join(labels) + ' together.')
            action_label = ('Use “' + values[0] + '”') if represented == ['text_type'] else education.get('action_label') or 'Use this recommendation'
            if len(items) > 1:
                action_label = 'Use these related updates'
        else:
            recommendation = assessment.get('recommendation') or 'Keep the current information for now.'
            action_label = 'Keep the current information'
        reason = assessment.get('rationale') or (reasons[0] if reasons else 'The available evidence does not establish a better value yet.')
        effects = list(dict.fromkeys(_education(fields[name])['effect'] for name in represented))
        rec = {'id': 'recommendation_' + _digest([target['id'], kind, family, *([alternative_id] if alternative_id else [])])[:24],
               'kind': kind, 'fields': represented, 'item_ids': [item['id'] for item in items], 'items': items,
               'question': education['question'], 'recommendation': recommendation, 'reason': reason,
               'reasons': reasons, 'strength': strength, 'strength_reason': assessment.get('strength_reason') or
               ('The suggested changes have source evidence; they have not been personally verified.' if kind == 'changes' else 'No supported replacement has been established. Keeping this does not verify it.'),
               'effect': ' '.join(effects) if kind == 'changes' else 'This closes this review question without changing or verifying your library information.',
               'purpose': education['purpose'], 'priority': 'optional' if all(_education(fields[name])['priority'] == 'optional' for name in represented) else 'important',
               'action_label': action_label, 'status': _status(items), 'evidence': evidence,
               'stale': any(item.get('stale') for item in items), 'reported_facts': []}
        if alternative_id:
            rec['reason'] += ' Other values were also suggested for these related fields; each choice stays separate.'
        result.append(rec)
    represented_fields = {name for rec in result for name in rec['fields']}
    for assessment in assessments:
        kind = assessment.get('kind')
        if kind == 'edition' and target['scope'] != 'work':
            continue
        names = [name for name in assessment.get('fields', []) if name in fields and (target['scope'] == 'work' or fields[name].get('editable', True))]
        if kind != 'edition' and (assessment.get('outcome') not in {'keep', 'unresolved'} or not names or represented_fields.intersection(names)):
            continue
        lead = fields[names[0]] if names else {'key': 'bibliography.edition', 'label': 'Book edition'}
        education = _education(lead)
        rec_kind = 'edition' if kind == 'edition' else 'question' if assessment.get('outcome') == 'unresolved' else 'keep'
        rec = {'id': 'recommendation_' + _digest([target['id'], rec_kind, sorted(names)])[:24],
               'kind': rec_kind, 'fields': names, 'items': [], 'item_ids': [],
               'question': 'Are these records describing the same book?' if kind == 'edition' else education['question'],
               'recommendation': assessment.get('recommendation') or 'Keep the current information for now.',
               'reason': assessment.get('rationale', ''), 'reasons': [assessment.get('rationale', '')],
               'strength': assessment.get('strength', 'needs_evidence'), 'strength_reason': assessment.get('strength_reason', ''),
               'effect': 'Keep the ISBN already recorded for this copy. This does not verify individual contributors or transfer page numbers.' if kind == 'edition' else 'Keep the recorded value without changing or verifying it.',
               'purpose': 'Identify the copy you are reading before checking its publication details.' if kind == 'edition' else education['purpose'],
               'priority': 'important' if kind == 'edition' else education['priority'],
               'action_label': 'Keep this ISBN' if kind == 'edition' else 'Keep this as it is',
               'evidence': copy.deepcopy(assessment.get('evidence', [])),
               'reported_facts': copy.deepcopy(assessment.get('reported_facts', [])),
               'assessment_id': assessment.get('id'), 'status': 'pending', 'stale': bool(assessment.get('stale')),
               'comparison': copy.deepcopy(assessment.get('comparison')),
               'edition_relationship': assessment.get('edition_relationship', 'unknown')}
        if kind == 'edition' and assessment.get('book_revision') and assessment['book_revision'] != context.get('book_revision'):
            rec['stale'] = True
        result.append(rec)
    decisions = draft.get('recommendation_decisions', {})
    # A later AI run may omit a useful no-change conclusion. Keep the handled
    # snapshot available for history and Undo without manufacturing metadata.
    current_ids = {rec['id'] for rec in result}
    for identity, decision in decisions.items():
        snapshot = decision.get('snapshot', {})
        if identity not in current_ids and snapshot.get('kind') in {'keep', 'edition', 'question'} and not snapshot.get('items'):
            rec = copy.deepcopy(snapshot)
            rec.update(history_only=True, status=decision.get('status', 'pending'))
            result.append(rec)
    for rec in result:
        rec['fingerprint'] = _fingerprint(context, rec)
        prior = decisions.get(rec['id'], {})
        rec['decision'] = copy.deepcopy(prior)
        rec['previous_decision'] = None
        if not rec['items'] and prior:
            if prior.get('fingerprint') == rec['fingerprint']:
                rec['status'] = prior.get('status', 'pending')
            else:
                rec['status'] = 'pending'
                rec['previous_decision'] = copy.deepcopy(prior)
        rec['strength_label'] = {'well_supported': 'Well supported', 'likely': 'Likely', 'needs_evidence': 'Needs more evidence'}.get(rec['strength'], 'Needs more evidence')
        rec['stale'] = bool(rec['stale'] or draft.get('stale') or not context.get('source_current', True))
    return sorted(result, key=lambda rec: (rec['priority'] == 'optional', rec['kind'] != 'edition', rec['id']))


def preview_recommendation(lib, context, draft, recommendation, selected_item_ids=None):
    """Use the citation engine against an in-memory overlay, never annotations."""
    from .citations import cite_passage
    fields = {field['key']: field for field in context['fields']}
    selected = set(recommendation['item_ids'] if selected_item_ids is None else selected_item_ids)
    if not selected.issubset(recommendation['item_ids']):
        raise ValueError('Choose changes from this recommendation only.')
    changes = {item['field']: {'value': copy.deepcopy(item.get('queued_value', item['value'])), 'evidence': 'Unsaved recommendation preview.', 'verified': False}
               for item in recommendation['items'] if item['kind'] == 'suggestion' and item['id'] in selected}
    before_display = {'title': context['target'].get('title'), 'credit': fields.get('attribution', fields.get('author', {})).get('value')}
    after_display = copy.deepcopy(before_display)
    for key, display_key in [('title', 'title'), ('author', 'credit'), ('attribution', 'credit')]:
        if key in changes:
            after_display[display_key] = changes[key]['value']
    preview = {'changes': [{'field': key, 'label': fields[key]['label'], 'before': display_value(fields[key]['value']),
                            'after': display_value(change['value'])} for key, change in changes.items()],
               'display': {'before': before_display, 'after': after_display},
               'citation': {'before': '', 'after': '', 'url': '', 'warnings': []}, 'limitations': []}
    if not any(key.startswith('bibliography.') for key in changes):
        return preview
    target = context['target']
    with lib._db() as db:
        if target['scope'] == 'passage':
            passage_id = target['id']
        else:
            column = 'work_id' if target['scope'] == 'work' else 'section_id'
            row = db.execute('SELECT id FROM passages WHERE ' + column + '=? AND boilerplate=0 ORDER BY ordinal LIMIT 1', (target['id'],)).fetchone()
            passage_id = row['id'] if row else None
    if not passage_id:
        preview['limitations'].append('A citation preview needs a readable passage in this target.')
        return preview
    proxy = copy.copy(lib)
    original_effective = lib._effective
    def effective(catalog):
        works, edits = original_effective(catalog)
        works, edits = copy.deepcopy(works), copy.deepcopy(edits)
        for key, change in changes.items():
            family, _, child = key.partition('.')
            old = edits.get((target['id'], family), {})
            event = {'field': family, 'target_id': target['id'], 'origin': 'user', 'status': 'provisional',
                     'evidence': change['evidence'], 'id': 'unsaved-preview'}
            if child:
                event['value'] = {**old.get('value', {}), child: copy.deepcopy(change['value'])}
                event['field_events'] = {**old.get('field_events', {}), child: {**event, 'value': {child: copy.deepcopy(change['value'])}}}
            else:
                event['value'] = copy.deepcopy(change['value'])
            edits[(target['id'], family)] = event
            if target['id'] in works and family in ('title', 'author'):
                works[target['id']][family] = change['value']
        return works, edits
    proxy._effective = effective
    try:
        before, after = cite_passage(lib, passage_id), cite_passage(proxy, passage_id)
        preview['citation'] = {'before': before.get('full_note', ''), 'after': after.get('full_note', ''),
                               'url': '/cite/' + passage_id, 'warnings': after.get('warnings', [])[:3]}
        preview['limitations'].append('This is an unsaved sample citation of the opening passage. Missing or unverified information remains provisional.')
    except (ValueError, KeyError, LookupError):
        preview['limitations'].append('This target needs a more specific citation before a reliable preview can be shown.')
    return preview
