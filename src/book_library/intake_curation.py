"""Conservative assistant corrections and provenance-preserving reversals.

Proposal validation makes data safe to review. This module separately decides
whether evidence is strong enough to apply it without a person's decision.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import unicodedata

from .storage import append_jsonl_batch, atomic_json, now, read_json, uid, writer

POLICY_VERSION = 'intake-evidence-1'


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _norm(value):
    return ' '.join(re.findall(r'\w+', unicodedata.normalize('NFKC', str(value)).casefold()))


def active_curation(events):
    """Filter append-only reversals without replacing absent values with null."""
    retracted = {identity for event in events if event.get('operation') == 'retract'
                 for identity in event.get('retracts', [])}
    return [event for event in events if event.get('operation') != 'retract' and event.get('id') not in retracted]


def _field_key(event):
    if event.get('automatic_field'):
        return event['automatic_field']
    if event.get('field') in ('bibliography', 'profile') and isinstance(event.get('value'), dict) and len(event['value']) == 1:
        return event['field'] + '.' + next(iter(event['value']))
    return event.get('field')


def _signature(target_id, proposal):
    # Wording or model generation IDs cannot resurrect an undone correction.
    key, value = proposal.get('field'), proposal.get('value')
    if key in ('bibliography.authors', 'bibliography.editors', 'bibliography.translators') and isinstance(value, list):
        from .citations import _display
        value = [_norm(_display(person)) for person in value]
    elif isinstance(key, str) and key.startswith('profile.') and isinstance(value, list):
        value = sorted({_norm(label) for label in value})
    elif isinstance(value, str):
        value = _norm(value)
    return _digest([target_id, key, value])


def _sources(context, proposal, result):
    """Revalidate references at application time against original source data."""
    from .review_ai import _safe_url, trusted_domains
    local = {source['id']: source for source in context.get('evidence', [])}
    external = {source['id']: source for source in (result.get('external_report') or {}).get('sources', [])}
    found = []
    for reference in proposal.get('evidence', []):
        identity = reference.get('source_id')
        if identity in local:
            source = local[identity]
            quote = reference.get('quote')
            if not isinstance(quote, str) or not quote.strip() or quote not in source.get('text', ''):
                return []
            found.append({**source, 'quote': quote, 'external': False})
        elif identity in external:
            source = external[identity]
            if (not _safe_url(source.get('url'), trusted_domains(context))
                    or source.get('url') != reference.get('url') or not source.get('cited_report_text')
                    or reference.get('quote')):
                return []
            found.append({**source, 'quote': source['cited_report_text'], 'external': True})
        else:
            return []
    return found


def _publication_zone(context, source):
    """A keyword elsewhere in a book is not its publication statement."""
    ordered = sorted(context.get('evidence', []), key=lambda item: item.get('ordinal', 0))
    if not ordered or source.get('role') not in ('publication_candidate', 'publication'):
        return False
    first = ordered[0].get('ordinal', 0)
    cutoff = first + 160
    for item in ordered:
        if item.get('kind') == 'heading' and re.match(r'^(?:table of contents|contents|introduction|preface|foreword|acknowledg|chapter\s+\d)', item.get('text', '').strip(), re.I):
            cutoff = min(cutoff, item.get('ordinal', cutoff))
            break
    return first <= source.get('ordinal', cutoff) < cutoff


def _assertion_text(text):
    return re.sub(r'\[[^\]]*\]\(https?://[^)]*\)', '', text).replace('*', '').replace('`', '')


_YEAR_LABEL = r'\b(?:publication (?:date|year)|(?:first |this edition |edition )?published)(?:\s+in)?\s*[:\-]?\s*'


def _labeled_assertion(key, value, text):
    """Recognize a labeled assertion, not an incidental/copyright year."""
    text = _assertion_text(text)
    escaped = re.escape(str(value).strip())
    if key == 'publisher':
        return bool(re.search(r'\b(?:published\s+by|publisher\s*:)\s*' + escaped + r'(?=$|[\s,.;])', text, re.I))
    if key == 'year':
        if not re.fullmatch(r'\d{4}', str(value)):
            return False
        return bool(re.search(_YEAR_LABEL + escaped + r'\b', text, re.I))
    if key == 'edition':
        return bool(re.fullmatch(r'(?:\w+[ -]){0,5}edition\.?', str(value), re.I)
                    and re.search(r'(?:^|[\n.;])\s*(?:edition\s*:\s*)?' + escaped + r'\.?\s*(?:$|[\n.;])', text, re.I))
    if key in ('title', 'format'):
        return bool(re.search(r'\b' + key + r'\s*:\s*' + escaped + r'(?=$|[\n.;])', text, re.I))
    return False


def _publication_assertion(context, key, value, source):
    return _publication_zone(context, source) and _labeled_assertion(key, value, source.get('text', ''))


def _copy_contradicts(context, key, value):
    if key == 'format':
        return _norm(value) != _norm(context['target'].get('copy_format'))
    for source in context.get('evidence', []):
        if not _publication_zone(context, source):
            continue
        text = _assertion_text(source.get('text', ''))
        if key == 'year':
            values = re.findall(_YEAR_LABEL + r'(\d{4})\b', text, re.I)
        elif key == 'publisher':
            values = re.findall(r'\b(?:published\s+by|publisher\s*:)\s*([^\n.;]+)', text, re.I)
        elif key == 'edition':
            values = re.findall(r'(?:^|[\n.;])\s*((?:\w+[ -]){0,5}edition)\.?\s*(?:$|[\n.;])', text, re.I)
        elif key == 'title':
            values = [text] if _norm(text) == _norm(context['target'].get('work_title')) else []
        else:
            values = []
        if any(_norm(observed) != _norm(value) for observed in values):
            return True
    return False


def _external_fact(context, proposal, sources):
    from .review_assessments import isbn, local_isbns
    key = proposal['field'].removeprefix('bibliography.')
    if key not in ('title', 'publisher', 'year', 'edition', 'format') or context['target']['scope'] != 'work':
        return False
    if _copy_contradicts(context, key, proposal['value']):
        return False
    if proposal.get('edition_match') is not True or proposal.get('edition_relationship') in ('related_format', 'different_edition'):
        return False
    number = isbn(context.get('book_identifiers', {}).get('isbn') or context['target'].get('isbn'))
    if not number:
        return False
    facts = proposal.get('reported_facts', [])
    for source in sources:
        if not source['external']:
            continue
        related = [fact for fact in facts if fact.get('source_id') == source['id']]
        source_numbers = {fact['value'] for fact in local_isbns([{'id': source['id'], 'text': source['quote']}])}
        if source_numbers != {number}:
            continue  # A paired-format summary does not bind each property.
        identifiers = [fact for fact in related if fact.get('kind') == 'isbn' and isbn(fact.get('value')) == number]
        values = [fact for fact in related if fact.get('kind') == key and _norm(fact.get('value')) == _norm(proposal['value'])
                  and isbn(fact.get('record_isbn')) == number]
        if identifiers and values and _labeled_assertion(key, proposal['value'], source['quote']):
            return True
    return False


def _credit_supported(context, proposal, sources):
    """Require a complete literal byline at a safe boundary or parser credit."""
    from .citations import _display
    key, value = proposal['field'], proposal['value']
    if proposal.get('relationship') != 'direct_credit' or not value:
        return False
    if any(source['external'] for source in sources):
        return False  # External report summaries cannot establish contribution ownership.
    scope = context['target']['scope']
    if scope != 'work' and (context.get('boundary_risk') or not context.get('coverage_complete') or proposal.get('coverage_complete') is False):
        return False
    if isinstance(value, list):
        names = [_display(person) for person in value]
    else:
        names = [str(value)]
    if not names or any(not name for name in names):
        return False
    target_sources = sorted((source for source in context.get('evidence', []) if source.get('in_target')), key=lambda source: source.get('ordinal', 0))
    boundary_ids = {source['id'] for source in [*target_sources[:4], *target_sources[-2:]]}
    role = 'editors' if key.endswith('editors') else 'translators' if key.endswith('translators') else 'authors'
    role_pattern = {'authors': r'(?:written\s+by|author\s*:|by)', 'editors': r'(?:edited\s+by|editors?\s*:)',
                    'translators': r'(?:translated\s+by|translators?\s*:)'}[role]
    if scope != 'work':
        bylines = {_norm(match.group(1)) for source in target_sources
                   if (match := re.fullmatch(role_pattern + r'\s+([^\n]{2,300})\.?', source.get('text', '').strip(), re.I))}
        if len(bylines) > 1:
            return False
    for source in sources:
        if source.get('kind') in ('quotation', 'blockquote', 'note'):
            continue
        if scope != 'work' and (not source.get('in_target') or source['id'] not in boundary_ids):
            continue
        if scope == 'work' and not _publication_zone(context, source):
            continue
        text = source.get('text', '').strip()
        statements = [text]
        if re.fullmatch(role_pattern, text, re.I):
            following = next((item for item in sources if not item['external'] and item.get('ordinal') == source.get('ordinal', -2) + 1
                              and item.get('kind') not in ('heading', 'note', 'quotation', 'blockquote')
                              and (item.get('in_target') if scope != 'work' else _publication_zone(context, item))), None)
            if following:
                statements.append(text + ' ' + following.get('text', '').strip())
        for statement in statements:
            match = re.fullmatch(role_pattern + r'\s+([^\n]{2,300})\.?', statement, re.I)
            if match:
                credited = match.group(1).strip().rstrip('.')
                credited_names = re.sub(r'\s+(?:and|&)\s+', ' ', credited, flags=re.I)
                if _norm(credited_names) == _norm(' '.join(names)):
                    return True
    # A recognized extraction parser has already tied this exact credit to
    # this complete target; it is not the model's claim about a roster.
    if role == 'authors' and scope != 'work':
        attribution = next((field for field in context['fields'] if field['key'] == 'attribution'), {})
        if attribution.get('origin') == 'source_byline' and _norm(attribution.get('value')) == _norm('; '.join(names)):
            return any(all(_norm(name) in _norm(source.get('text', '')) for name in names) and source.get('in_target') for source in sources)
    return False


def _category_supported(category, sources):
    texts = '\n'.join(source['quote'] for source in sources)
    signals = {
        'editorial': r'\b(?:purpose|arrang\w*|how to use|this (?:book|volume|introduction)|intended (?:use|audience))\b',
        'commentary': r'\b(?:means?|interpret\w*|commentary|explains?|significance)\b',
        'translation_note': r'\b(?:translat\w*|Hebrew|Greek)\b',
        'caption': r'\b(?:figure|plate|photograph|image|illustration)\s*\d',
        'index': r'\bindex\b', 'reference': r'\b(?:bibliograph\w*|references|works cited)\b',
        'quotation': r'\b(?:quoted from|quotation|excerpt from)\b',
    }
    if category == 'poetry':
        return any(source.get('kind') == 'poetry' or len(source['quote'].splitlines()) >= 3 for source in sources)
    if category == 'scripture':
        return any(source.get('kind') in ('scripture', 'verse') for source in sources)
    if category == 'prose':
        return any(source.get('kind') == 'paragraph' and len(source['quote'].split()) >= 15 for source in sources)
    return bool(category in signals and re.search(signals[category], texts, re.I))


def _distinct_kinds(kinds, sources):
    # Prose is the fallback for more specific prose kinds, not another kind
    # to count alongside an introduction or commentary in the same paragraph.
    if 'prose' in kinds and kinds.intersection({'editorial', 'commentary', 'reference', 'translation_note'}):
        return False
    options = {kind: {source['id'] for source in sources if _category_supported(kind, [source])} for kind in kinds}
    def assign(remaining, used):
        if not remaining:
            return True
        first, *rest = remaining
        return any(assign(rest, used | {identity}) for identity in options[first] - used)
    return assign(sorted(kinds, key=lambda kind: len(options[kind])), set())


def _support_rule(context, proposal, result):
    sources = _sources(context, proposal, result)
    if not sources:
        return None, 'The supporting references cannot be validated against this source.'
    key, value = proposal['field'], proposal['value']
    if any(source['external'] for source in sources):
        return ('matched_external_record', '') if _external_fact(context, proposal, sources) else (None, 'External evidence does not bind this value to the same edition record.')
    if key in ('title', 'bibliography.title'):
        target = sorted((s for s in context['evidence'] if s.get('in_target') and s.get('kind') == 'heading'), key=lambda s: s.get('ordinal', 0))
        first_heading = target[0]['id'] if target else None
        matches = [s for s in sources if _norm(value) == _norm(s.get('text')) and
                   (s['id'] == first_heading if context['target']['scope'] != 'work' else
                    _publication_zone(context, s) and _norm(value) == _norm(context['target'].get('work_title')))]
        return ('printed_target_title', '') if matches else (None, 'The title does not match the target’s actual heading or title statement.')
    if key in ('author', 'attribution', 'bibliography.authors', 'bibliography.editors', 'bibliography.translators'):
        return ('scoped_source_credit', '') if _credit_supported(context, proposal, sources) else (None, 'A recognized person-role-contribution relationship has not been established.')
    if key in ('bibliography.publisher', 'bibliography.year', 'bibliography.edition'):
        publication_key = key.split('.')[1]
        if (context['target']['scope'] == 'work' and not _copy_contradicts(context, publication_key, value)
                and any(_publication_assertion(context, publication_key, value, source) for source in sources)):
            return 'labeled_publication_fact', ''
        return None, 'The proposed value is not bound to an unambiguous publication statement for this copy.'
    if key == 'bibliography.format' and _norm(value) == _norm(context['target'].get('copy_format')):
        return 'actual_file_format', ''
    target_sources = [source for source in sources if source.get('in_target') and not source.get('fragment')]
    if key == 'text_type':
        if proposal.get('relationship') != 'subject_classification' or not target_sources:
            return None, 'Automatic writing categories need scoped target evidence.'
        if value != 'mixed' and (not context.get('coverage_complete') or proposal.get('coverage_complete') is False):
            return None, 'A uniform writing category needs complete target evidence.'
        if value == 'scripture':
            body = [source for source in context['evidence'] if source.get('in_target') and source.get('kind') not in ('heading', 'pagebreak')]
            if not body or any(source.get('kind') not in ('scripture', 'verse') for source in body):
                return None, 'A Bible reference or quotation does not establish that the entire target is Scripture.'
        if value == 'mixed':
            kinds = set(proposal.get('content_kinds', [])) - {'mixed', 'unknown'}
            if len(kinds) >= 2 and len({s['id'] for s in target_sources}) >= 2 and _distinct_kinds(kinds, target_sources):
                return 'supported_mixed_judgment', ''
        elif _category_supported(value, target_sources):
            return 'complete_target_judgment', ''
        return None, 'The excerpts do not demonstrate the proposed kind of writing.'
    if key.startswith('profile.'):
        text = ' ' + _norm(' '.join(source['quote'] for source in target_sources)) + ' '
        if (proposal.get('relationship') == 'subject_classification' and isinstance(value, list) and value
                and all(' ' + _norm(label) + ' ' in text for label in value)):
            return 'grounded_research_labels', ''
        return None, 'Every automatic research label must be grounded in the inspected target excerpts.'
    return None, 'This field is available for manual review but has no automatic evidence rule.'


def _eligible(context, draft, proposal, result, events):
    from .review import validate_field_value
    fields = {field['key']: field for field in context['fields']}
    key = proposal.get('field')
    field = fields.get(key)
    if not field or not field.get('editable', True):
        return None, 'This field belongs to another correction scope.'
    try:
        validate_field_value(field, proposal.get('value'))
    except (ValueError, TypeError, KeyError):
        return None, 'The proposed value is not valid for this field.'
    if proposal.get('stale') or proposal.get('scope_supported') is not True:
        return None, 'The proposal is stale or does not establish its full scope.'
    if proposal.get('ai_provenance', {}).get('revision', context['revision']) != context['revision']:
        return None, 'The proposal was generated against earlier information.'
    if proposal.get('model_strength', proposal.get('strength')) != 'well_supported' or not str(proposal.get('rationale', '')).strip():
        return None, 'The proposal lacks an explicit well-supported assessment and explanation.'
    if field.get('origin') == 'user' or field.get('status') in ('confirmed', 'disputed'):
        return None, 'An existing user edit, verified value, or disputed value is protected.'
    if key in draft.get('changes', {}):
        return None, 'A manual draft already exists for this field.'
    family = {key, *field.get('related_fields', [])}
    for decision in draft.get('decisions', {}).values():
        if decision.get('snapshot', {}).get('field') in family and decision.get('decision') in ('accepted', 'rejected', 'kept', 'later', 'saved'):
            return None, 'An existing human decision is protected.'
    for decision in draft.get('recommendation_decisions', {}).values():
        if family.intersection(decision.get('snapshot', {}).get('fields', [])) and decision.get('status') not in (None, 'pending'):
            return None, 'An existing human recommendation decision is protected.'
    for finding in result.get('unresolved', []):
        if finding.get('field') in family or finding.get('category') == 'edition_mismatch':
            return None, 'An unresolved finding conflicts with automatic saving.'
    if any(a.get('edition_relationship') == 'different_edition' for a in result.get('assessments', [])):
        return None, 'The review reports a conflicting edition.'
    if context['target']['scope'] == 'work' and not key.startswith('profile.'):
        if any(a.get('kind') == 'edition' and a.get('edition_relationship', 'unknown') == 'unknown'
               and (a.get('comparison') or {}).get('compared_isbn') for a in result.get('assessments', [])):
            return None, 'The publication identifiers have an unresolved relationship.'
    signature = _signature(context['target']['id'], proposal)
    retracted = {identity for event in events if event.get('operation') == 'retract' for identity in event.get('retracts', [])}
    if any(event.get('id') in retracted and (event.get('automatic_signature') == signature or
           _signature(event.get('target_id'), {'field': event.get('automatic_field'), 'value': event.get('automatic_after')}) == signature)
           for event in events if event.get('automatic_field')):
        return None, 'This automatic finding was undone; it will not be applied again.'
    return _support_rule(context, proposal, result)


def _receipt_path(lib, intake_id, request_id, target_id):
    return lib.state / 'intake-applications' / (_digest([intake_id, request_id, target_id]) + '.json')


def _receipt(intake_id, request_id, target_id, events, blocked=()):
    if events and not blocked:
        blocked = events[0].get('automatic_blocked', [])
    applied = [{'event_id': e['id'], 'field': e['automatic_field'], 'value': copy.deepcopy(e['automatic_after']),
                'before': copy.deepcopy(e['automatic_before']), 'rule': e['automatic_rule']} for e in events]
    return {'intake_id': intake_id, 'request_id': request_id, 'target_id': target_id, 'saved': bool(events),
            'applied': applied, 'fields': [e['automatic_field'] for e in events], 'blocked': list(blocked),
            'refresh_required': any(e['field'] != 'bibliography' for e in events),
            'needs_review': bool(blocked or events and events[0].get('automatic_needs_review')), 'created_at': now()}


def _context_guard(context):
    return {'source': context.get('source_fingerprint'), 'work_title': context['target'].get('work_title'),
            'fields': {field['key']: _digest({key: field.get(key) for key in
                        ('value', 'raw_value', 'status', 'origin', 'annotation_id', 'inherited', 'inherited_value')})
                       for field in context['fields']}}


def _reconcile_empty_draft(lib, target_id, events):
    """Do not make remaining review questions stale solely through our batch.

The event guard also makes recovery after a committed-but-unrecorded batch safe:
intervening human/catalog/source changes stop reconciliation. Manual drafts are
never rebased or otherwise changed here.
"""
    if not events:
        return
    from .review import review_context, _load, _path
    path = _path(lib, target_id)
    if not path.exists():
        return
    context = review_context(lib, target_id)
    draft = _load(lib, target_id, context)
    if draft.get('changes') or not context.get('source_current'):
        return
    before = events[0].get('automatic_context_guard')
    if not before or draft['revision'] not in (events[0]['automatic_revision'], context['revision']):
        return
    current = _context_guard(context)
    changed = {event['automatic_field']: event for event in events}
    expected_title = changed['title']['automatic_after'] if context['target']['scope'] == 'work' and 'title' in changed else before['work_title']
    if current['source'] != before['source'] or current['work_title'] != expected_title:
        return
    if any(current['fields'].get(key) != fingerprint for key, fingerprint in before['fields'].items() if key not in changed):
        return
    fields = {field['key']: field for field in context['fields']}
    if any(fields.get(key, {}).get('annotation_id') != event['id'] for key, event in changed.items()):
        return
    signatures = {event['automatic_signature'] for event in events}
    suggestions = []
    for proposal in draft.get('suggestions', []):
        if _signature(target_id, proposal) in signatures:
            continue
        proposal = copy.deepcopy(proposal)
        related = {proposal.get('field'), *proposal.get('related_fields', [])}
        related.update(fields.get(proposal.get('field'), {}).get('related_fields', []))
        if related.intersection(changed):
            proposal['stale'] = True
        elif draft.get('suggestion_revision') == events[0]['automatic_revision']:
            # Replaying a saved result after our commit makes store_suggestions
            # conservatively mark it stale. The guard proves that only this
            # batch changed, so unrelated findings from that result remain current.
            proposal['stale'] = False
        suggestions.append(proposal)
    if suggestions == draft.get('suggestions', []) and draft['revision'] == context['revision']:
        return
    draft.update(suggestions=suggestions, revision=context['revision'], version=draft['version'] + 1, updated_at=now())
    atomic_json(path, draft)


def apply_automatic(lib, target_id, result, *, intake_id, request_id, revision):
    """Apply an independently eligible subset atomically; preserve manual drafts."""
    from .review import review_context, _load, ReviewConflict
    path = _receipt_path(lib, intake_id, request_id, target_id)
    with writer(lib.state):
        prior = read_json(path)
        if prior is not None:
            events = [event for event in lib._curation() if event.get('automatic_intake_id') == intake_id
                      and event.get('automatic_request_id') == request_id and event.get('target_id') == target_id]
            _reconcile_empty_draft(lib, target_id, events)
            return {**prior, 'replay': True}
        history = lib._curation()
        committed = [event for event in history if event.get('automatic_intake_id') == intake_id
                     and event.get('automatic_request_id') == request_id and event.get('target_id') == target_id
                     and event.get('operation') != 'retract']
        if committed:
            receipt = _receipt(intake_id, request_id, target_id, committed)
            _reconcile_empty_draft(lib, target_id, committed)
            atomic_json(path, receipt)
            return {**receipt, 'replay': True}
        context = review_context(lib, target_id)
        if revision != context['revision'] or not context.get('source_current'):
            raise ReviewConflict('The source or information changed before automatic saving. Resume after reviewing the updated source.')
        draft = _load(lib, target_id, context)
        fields = {field['key']: field for field in context['fields']}
        events, blocked = [], []
        proposals = result.get('suggestions', [])
        if not isinstance(proposals, list) or len(proposals) > 80:
            raise ValueError('Automatic application needs a bounded list of suggestions.')
        counts = {key: sum(p.get('field') == key for p in proposals if isinstance(p, dict)) for key in fields}
        for proposal in proposals:
            if not isinstance(proposal, dict):
                continue
            key = proposal.get('field')
            if counts.get(key, 0) > 1:
                blocked.append({'field': key, 'reason': 'Competing values for one field require a decision.'})
                continue
            rule, reason = _eligible(context, draft, proposal, result, history)
            if not rule:
                blocked.append({'field': key or 'unknown', 'reason': reason})
                continue
            field = fields[key]
            value = copy.deepcopy(proposal['value'])
            if key in ('bibliography.authors', 'bibliography.editors', 'bibliography.translators') and isinstance(value, list):
                # A plain printed name does not prove its given/family structure.
                from .citations import _display
                known = {_norm(_display(person)): person for person in field.get('raw_value') or []}
                value = [copy.deepcopy(known[_norm(_display(person))]) if _norm(_display(person)) in known
                         else {'literal': _display(person)} for person in value]
            if value == field.get('raw_value'):
                continue
            family, _, subfield = key.partition('.')
            evidence = '\n'.join([proposal['rationale'], *[reference.get('quote') or reference.get('summary') or '' for reference in proposal.get('evidence', [])]])[:4000]
            event = lib._validated_annotation(target_id, {
                'field': family, 'value': {subfield: value} if subfield else value,
                'origin': 'codex', 'status': 'provisional', 'evidence': evidence,
                'automatic_intake_id': intake_id, 'automatic_request_id': request_id,
                'automatic_field': key, 'automatic_field_label': field['label'],
                'automatic_before': {name: copy.deepcopy(field.get(name)) for name in ('raw_value', 'value', 'annotation_id', 'origin', 'status', 'inherited', 'inherited_value')},
                'automatic_after': value, 'automatic_rule': rule, 'automatic_policy': POLICY_VERSION,
                'automatic_signature': _signature(target_id, proposal), 'automatic_revision': revision,
                'automatic_evidence': copy.deepcopy(proposal.get('evidence', [])),
                'ai_provenance': copy.deepcopy(proposal.get('ai_provenance', {'model': result.get('model')})),
            })
            events.append(event)
        needs_review = bool(draft.get('changes') or blocked or result.get('unresolved') or any(
            a.get('outcome') == 'unresolved' or a.get('strength') == 'needs_evidence' for a in result.get('assessments', [])))
        if events:
            events[0]['automatic_context_guard'] = _context_guard(context)
            events[0]['automatic_blocked'] = copy.deepcopy(blocked)
            events[0]['automatic_needs_review'] = needs_review
        append_jsonl_batch(lib.state / 'curation.jsonl', events)
        _reconcile_empty_draft(lib, target_id, events)
        receipt = _receipt(intake_id, request_id, target_id, events, blocked)
        receipt['needs_review'] = needs_review
        atomic_json(path, receipt)
        return receipt


def _latest_ids(lib, events):
    # Only exact current field events may be reversed; later edits are retained.
    _, edits = lib._effective(lib._catalog())
    current = {}
    for (target, family), event in edits.items():
        if family in ('bibliography', 'profile'):
            for field, detail in event.get('field_events', {}).items():
                current[(target, family + '.' + field)] = detail.get('id')
        else:
            current[(target, family)] = event.get('id')
    return current


def automatic_changes(lib, intake_id):
    events = lib._curation()
    retracted = {identity for event in events if event.get('operation') == 'retract' for identity in event.get('retracts', [])}
    current = _latest_ids(lib, events)
    result = []
    for event in events:
        if event.get('automatic_intake_id') != intake_id or event.get('operation') == 'retract':
            continue
        undone = event['id'] in retracted
        active = current.get((event['target_id'], event['automatic_field'])) == event['id'] and not undone
        before = copy.deepcopy(event.get('automatic_before', {}))
        value = before.get('raw_value')
        result.append({'id': event['id'], 'event_id': event['id'], 'target_id': event['target_id'],
                       'field': event['automatic_field'], 'field_label': event.get('automatic_field_label', event['automatic_field']),
                       'before': before, 'before_display': 'Inherited' if before.get('inherited') else 'Not recorded' if value is None else value,
                       'after': copy.deepcopy(event['automatic_after']), 'value': copy.deepcopy(event['automatic_after']),
                       'evidence': event['evidence'], 'rule': event['automatic_rule'], 'created_at': event['created_at'],
                       'status': 'undone' if undone else 'active' if active else 'superseded', 'undone': undone, 'undoable': active,
                       'review_url': '/review/' + event['target_id']})
    return result


def undo_automatic(lib, intake_id, event_id=None, *, expected_version=None):
    """Reverse current assistant events without creating fake replacement facts."""
    with writer(lib.state):
        job = None
        from .intake import _load, _check_version
        try:
            job = _load(lib, intake_id)
        except ValueError:
            if expected_version is not None:
                raise
        if job is not None and expected_version is not None:
            _check_version(job, expected_version)
        history = lib._curation()
        candidates = [event for event in history if event.get('automatic_intake_id') == intake_id
                      and event.get('operation') != 'retract' and (event_id is None or event['id'] == event_id)]
        if event_id and not candidates:
            raise ValueError('This automatic change does not belong to this intake.')
        retracted = {identity for event in history if event.get('operation') == 'retract' for identity in event.get('retracts', [])}
        current = _latest_ids(lib, history)
        eligible_keys = {(event['target_id'], event['automatic_field']) for event in candidates
                         if event['id'] not in retracted and current.get((event['target_id'], event['automatic_field'])) == event['id']}
        records, undone, skipped = [], [], []
        for event in candidates:
            if event['id'] in retracted:
                continue
            if (event_id is not None and current.get((event['target_id'], event['automatic_field'])) != event['id']
                    or event_id is None and (event['target_id'], event['automatic_field']) not in eligible_keys):
                skipped.append({'event_id': event['id'], 'reason': 'A later edit is protected.'})
                continue
            records.append({'id': uid('retraction'), 'operation': 'retract', 'retracts': [event['id']],
                            'target_id': event['target_id'], 'field': event['field'], 'value': None,
                            'origin': 'user', 'status': 'provisional', 'evidence': 'Explicitly undid this automatic intake change.',
                            'intake_id': intake_id, 'created_at': now()})
            undone.append(event['id'])
        refresh = any(event['id'] in undone and event['field'] != 'bibliography' for event in candidates)
        if job is not None and records:
            from .intake import _save
            # Publish the refresh obligation before committing reversals. A
            # crash can cause an extra local refresh, never lose a needed one.
            job['refresh_pending'] = bool(job.get('refresh_pending') or refresh)
            _save(lib, job)
        append_jsonl_batch(lib.state / 'curation.jsonl', records)
        return {'undone': undone, 'skipped': skipped, 'refresh_required': refresh}
