"""Read-only, stable review items over drafts and evidence-backed findings.

Workflow decisions are deliberately separate from both curation and generated
prose. Rephrasing an explanation must not undo a person's decision.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import unicodedata


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def _digest(value):
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def item_id(target_id, kind, field, value=None):
    identity = [target_id, kind, field]
    if kind == 'suggestion':
        identity.append(value)
    return 'item_' + _digest(identity)[:24]


def _unique(values):
    return list({_canonical(value): value for value in values}.values())


def _fact(fact):
    value = unicodedata.normalize('NFKC', str(fact.get('value', '')))
    if fact.get('kind') == 'isbn':
        value = re.sub(r'[^0-9X]', '', value.upper())
    else:
        value = ' '.join(value.casefold().split())
    return {'source_id': fact.get('source_id'), 'kind': fact.get('kind'), 'value': value}


def comparison_fingerprint(context, item):
    """Compare pertinent facts, never generation IDs or explanatory wording."""
    field = next((f for f in context['fields'] if f['key'] == item['field']), {})
    source_map = {source['id']: source for source in context.get('evidence', [])}
    references = []
    for evidence in item.get('evidence', []):
        source = source_map.get(evidence.get('source_id'), {})
        references.append({
            'id': evidence.get('source_id'), 'url': evidence.get('url'),
            'content': source.get('content_hash') or (_digest(source['text']) if source.get('text') else None),
            'edition_match': evidence.get('edition_match'),
        })
    metadata = {key: field.get(key) for key in
                ('value', 'raw_value', 'status', 'origin', 'evidence', 'inherited', 'inherited_value')}
    bibliography = item['field'].startswith('bibliography.') or item['field'] in ('title', 'author', 'attribution')
    return _digest({
        'field': metadata, 'proposed_value': item.get('value'),
        'membership': context.get('source_fingerprint') or _digest([
            [s['id'], s.get('content_hash') or s.get('text')] for s in context.get('evidence', []) if s.get('in_target')]),
        'scope': context['target'].get('scope'), 'source_current': context.get('source_current', True),
        'identifiers': context.get('book_identifiers') if bibliography else None,
        'categories': sorted(set(item.get('categories', [])) - {'other'}),
        'references': sorted(_unique(references), key=_canonical),
        'reported_facts': sorted(_unique([_fact(fact) for fact in item.get('reported_facts', [])]), key=_canonical),
    })


def item_snapshot(item):
    return {key: copy.deepcopy(item[key]) for key in
            ('id', 'kind', 'field', 'value', 'reasons', 'evidence', 'categories',
             'reported_facts', 'proposal_id', 'ai_provenance', 'related_fields', 'stale') if key in item}


def review_items(context, draft):
    """Return distinct field decisions, including preserved handled history."""
    target_id = context['target']['id']
    fields = {field['key']: field for field in context['fields']}
    items = {}
    for proposal in draft.get('suggestions', []):
        field = proposal.get('field')
        if field not in fields:
            continue
        identity = item_id(target_id, 'suggestion', field, proposal.get('value'))
        item = items.setdefault(identity, {
            'id': identity, 'kind': 'suggestion', 'field': field, 'value': copy.deepcopy(proposal.get('value')),
            'reasons': [], 'evidence': [], 'categories': [], 'reported_facts': [],
            'proposal_id': proposal.get('id'), 'ai_provenance': copy.deepcopy(proposal.get('ai_provenance', {})),
            'related_fields': list(fields[field].get('related_fields', [])), 'stale': bool(proposal.get('stale')),
        })
        if proposal.get('rationale'):
            item['reasons'].append(proposal['rationale'])
        item['evidence'].extend(copy.deepcopy(proposal.get('evidence', [])))
        item['reported_facts'].extend(copy.deepcopy(proposal.get('reported_facts', [])))
    for finding in draft.get('unresolved', []):
        if not isinstance(finding, dict) or finding.get('field') not in fields:
            continue
        field = finding['field']
        identity = item_id(target_id, 'question', field)
        item = items.setdefault(identity, {
            'id': identity, 'kind': 'question', 'field': field, 'reasons': [], 'evidence': [],
            'categories': [], 'reported_facts': [], 'related_fields': list(fields[field].get('related_fields', [])),
            'stale': False,
        })
        if finding.get('reason'):
            item['reasons'].append(finding['reason'])
        if finding.get('category'):
            item['categories'].append(finding['category'])
        item['evidence'].extend(copy.deepcopy(finding.get('evidence', [])))
        item['reported_facts'].extend(copy.deepcopy(finding.get('reported_facts', [])))
    decisions = draft.get('decisions', {})
    for identity, decision in decisions.items():
        snapshot = decision.get('snapshot')
        if identity not in items and isinstance(snapshot, dict) and snapshot.get('field') in fields:
            items[identity] = copy.deepcopy(snapshot)
            items[identity]['from_history'] = True
    for identity, item in items.items():
        for key in ('reasons', 'evidence', 'categories', 'reported_facts'):
            item[key] = _unique(item.get(key, []))
        fingerprint = comparison_fingerprint(context, item)
        decision = decisions.get(identity, {})
        status = decision.get('decision', 'pending')
        reopened = bool(decision and status != 'pending' and decision.get('fingerprint') != fingerprint)
        if status == 'saved' and (item.get('from_history') or item.get('stale')):
            # A receipt describes an applied correction, not a request to redo
            # that correction after later edits. Only newly returned, current
            # evidence may make the same proposed value actionable again.
            reopened = False
        if status == 'accepted' and item['field'] not in draft.get('changes', {}):
            status = 'pending'
        item.update(status='pending' if reopened else status, fingerprint=fingerprint,
                    reopened=reopened, previous_decision=copy.deepcopy(decision) if reopened else None,
                    decision=copy.deepcopy(decision), stale=bool(item.get('stale') or not context.get('source_current', True)
                        or item.get('from_history') and item['kind'] == 'suggestion' and reopened))
        if item['status'] == 'accepted' and item['field'] in draft.get('changes', {}):
            item['queued_value'] = copy.deepcopy(draft['changes'][item['field']]['value'])
            item['edited'] = item['queued_value'] != item.get('value')
        if item['status'] == 'saved' and 'saved_value' in decision:
            item['saved_value'] = copy.deepcopy(decision['saved_value'])
            item['saved_evidence'] = decision.get('saved_evidence', '')
            item['edited'] = item['saved_value'] != item.get('value')
    return list(items.values())
