"""Evidence-bound explanations and ISBN comparisons; never correction writes."""
from __future__ import annotations

import copy
import hashlib
import json
import re

RELATIONSHIPS = ('same_publication', 'related_format', 'different_edition', 'unknown')
STRENGTHS = ('well_supported', 'likely', 'needs_evidence')


def assessment_schema(keys, evidence, fact):
    string = {'type': 'string'}
    props = {'kind': {'type': 'string', 'enum': ['edition', 'field']},
             'fields': {'type': 'array', 'maxItems': 8, 'items': {'type': 'string', 'enum': keys}},
             'outcome': {'type': 'string', 'enum': ['keep', 'change', 'unresolved']},
             'recommendation': string, 'rationale': string,
             'strength': {'type': 'string', 'enum': list(STRENGTHS)}, 'strength_reason': string,
             'evidence': {'type': 'array', 'maxItems': 8, 'items': evidence},
             'reported_facts': {'type': 'array', 'maxItems': 12, 'items': fact},
             'edition_relationship': {'type': 'string', 'enum': list(RELATIONSHIPS)}}
    return {'type': 'object', 'additionalProperties': False, 'properties': props, 'required': list(props)}


def isbn(value):
    """Canonicalize and validate ISBN-10/13; arbitrary numbers are not ISBNs."""
    value = re.sub(r'[^0-9X]', '', str(value).upper())
    if len(value) == 13 and value.startswith(('978', '979')) and value.isdigit() and sum(int(n) * (1 if i % 2 == 0 else 3) for i, n in enumerate(value)) % 10 == 0:
        return value
    if len(value) == 10 and value[:9].isdigit() and (value[-1].isdigit() or value[-1] == 'X'):
        digits = [int(x) if x != 'X' else 10 for x in value]
        if sum((10-i)*n for i, n in enumerate(digits)) % 11 == 0:
            prefix = '978' + value[:9]
            return prefix + str((-sum(int(n)*(1 if i % 2 == 0 else 3) for i, n in enumerate(prefix))) % 10)
    return ''


def local_isbns(evidence):
    found = []
    for source in evidence:
        if source.get('url'):
            continue
        for match in re.finditer(r'\bISBN(?:-1[03])?\s*:?\s*((?:97[89][\s-]?)?(?:\d[\s-]?){9}[\dX])\b', source.get('text', ''), re.I):
            number = isbn(match.group(1))
            if number and not any(x['value'] == number and x['source_id'] == source['id'] for x in found):
                found.append({'source_id': source['id'], 'kind': 'isbn', 'value': number})
    return found


def _format(value):
    value = str(value).casefold()
    if any(word in value for word in ('ebook', 'e-book', 'epub', 'digital', 'pdf')):
        return 'digital'
    if any(word in value for word in ('hardback', 'hardcover', 'paperback', 'print', 'alk. paper')):
        return 'print'
    return ''


def _edition(value):
    value = str(value).casefold()
    for word, number in (('first', '1'), ('second', '2'), ('third', '3'), ('fourth', '4')):
        value = re.sub(r'\b'+word+r'\b', number, value)
    value = re.sub(r'(\d)(?:st|nd|rd|th)\b', r'\1', value)
    return re.sub(r'\W|\bedition\b|\bed\b', '', value)


def comparison(context, facts, evidence, requested='unknown'):
    """Only retain relationship conclusions supported by actual record bridges."""
    from .review_ai import _identifiers, _normalized
    identifiers = _identifiers(context)
    recorded = isbn(identifiers.get('isbn'))
    if not recorded:
        return None
    source_map = {source['id']: source for source in evidence}
    facts = [*local_isbns(evidence), *copy.deepcopy(facts)]
    numbers = list(dict.fromkeys(isbn(f['value']) for f in facts if f.get('kind') == 'isbn' and isbn(f.get('value'))))
    other = next((value for value in numbers if value != recorded), '')
    records, conflicts, edition_conflicts = [], [], []
    for number in (recorded, other):
        if not number:
            continue
        ids = list(dict.fromkeys(f['source_id'] for f in facts if f.get('kind') == 'isbn' and isbn(f.get('value')) == number))
        record = {key: '' for key in ('title', 'format', 'publisher', 'year', 'edition')}
        if number == recorded:
            record.update({key: str(identifiers.get(key) or '') for key in ('title', 'publisher', 'year', 'edition')})
        # Facts explicitly tied to this ISBN are stronger than co-occurrence.
        # A provider may list both print and ebook ISBNs; its single format label
        # must not silently be assigned to both.
        for key in record:
            choices = [f for f in facts if f.get('kind') == key and
                       (isbn(f.get('record_isbn')) == number or (not f.get('record_isbn') and f.get('source_id') in ids and
                        len({isbn(g.get('value')) for g in facts if g.get('kind') == 'isbn' and g.get('source_id') == f.get('source_id')}) == 1))]
            local = [f for f in choices if not source_map.get(f['source_id'], {}).get('url')]
            publishers = [f for f in choices if source_map.get(f['source_id'], {}).get('source_kind') == 'publisher']
            if local or publishers or choices:
                record[key] = (local or publishers or choices)[0]['value']
                alternatives = [f['value'] for f in choices if _normalized(f['value']) != _normalized(record[key])]
                if alternatives:
                    conflicts.append(f'Records disagree about {key} for ISBN {number}: {record[key]} / {" / ".join(dict.fromkeys(alternatives))}. The copy and publisher take priority.')
                    if key == 'edition' and any(_edition(value) != _edition(record[key]) for value in alternatives):
                        edition_conflicts.append(number)
        local_ids = [key for key in ids if not source_map.get(key, {}).get('url')]
        record.update(isbn=number, source_ids=ids,
                      origin='Library record' if number == recorded else 'Printed in this copy' if local_ids else 'External listing')
        records.append(record)
    relation = 'unknown'
    if not other and recorded in numbers and not edition_conflicts:
        relation = 'same_publication'
    if other:
        first, second = records
        first_format, second_format = _format(first['format']), _format(second['format'])
        paired = any({recorded, other}.issubset({isbn(f.get('value')) for f in facts if f.get('source_id') == source and f.get('kind') == 'isbn'}) for source in source_map)
        printed_bridge = any(isbn(f.get('value')) == other for f in local_isbns(evidence))
        same_title = _normalized(first['title']) == _normalized(second['title']) and bool(first['title'])
        same_year = _normalized(first['year']) == _normalized(second['year']) and bool(first['year'])
        different_edition = first['edition'] and second['edition'] and _edition(first['edition']) != _edition(second['edition'])
        if requested == 'different_edition' and different_edition and not edition_conflicts:
            relation = 'different_edition'
        elif not different_edition and not edition_conflicts and (paired or printed_bridge and same_title and same_year) and first_format and second_format and first_format != second_format:
            relation = 'related_format'
    differences = []
    if len(records) == 2:
        for key, label in (('format', 'Format'), ('edition', 'Edition statement'), ('year', 'Publication year'), ('publisher', 'Publisher')):
            a, b = records[0][key], records[1][key]
            if a and b and _normalized(a) != _normalized(b):
                differences.append(f'{label}: {a} / {b}.')
    unknowns = [*conflicts, 'A comparison of publication records does not establish identical full text or transferable page numbers.']
    if relation == 'unknown':
        unknowns.insert(0, 'The available evidence does not yet establish how these records are related.')
        if len(records) == 2 and different_edition:
            unknowns.insert(1, 'The edition statements differ; a format difference does not resolve that conflict.')
    return {'recorded_isbn': recorded, 'compared_isbn': other, 'relationship': relation,
            'records': records, 'known_differences': differences, 'unknowns': unknowns,
            'copy_note': ' · '.join(str(context.get('target', {}).get(key) or '') for key in ('source_origin', 'copy_format') if context.get('target', {}).get(key))}


def _text(item, key, limit):
    value = item.get(key, '')
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError('Assessment explanations must be bounded text.')
    return value.strip()


def validate_assessments(result, context, evidence, suggestions=()):
    """Validate mixed local/external citations and build display-safe comparisons."""
    from .review_ai import _cited_evidence, _reported_facts
    fields = {field['key'] for field in context['fields']}
    source_map = {source['id']: source for source in evidence}
    accepted = []
    for raw in (result.get('assessments') or [])[:8]:
        try:
            if not isinstance(raw, dict) or raw.get('kind') not in ('edition', 'field') or raw.get('outcome') not in ('keep', 'change', 'unresolved'):
                continue
            keys = raw.get('fields', [])
            if not isinstance(keys, list) or len(keys) > 8 or any(key not in fields for key in keys):
                continue
            if raw['kind'] == 'field' and not keys:
                continue
            citations = raw.get('evidence', [])
            raw_facts = raw.get('reported_facts', [])
            if not isinstance(citations, list) or len(citations) > 8 or not isinstance(raw_facts, list) or len(raw_facts) > 12:
                continue
            cited, facts = [], []
            for external in (False, True):
                group = [c for c in citations if isinstance(c, dict) and bool(source_map.get(c.get('source_id'), {}).get('url')) == external]
                ids = {c.get('source_id') for c in group}
                group_facts = [fact for fact in raw_facts if isinstance(fact, dict) and fact.get('source_id') in ids]
                facts.extend(_reported_facts(group_facts, source_map, ids, external=external, report=context.get('external_report_text', '')))
                cited.extend(_cited_evidence(group, source_map, context, external=external))
            if any(not isinstance(fact, dict) or fact.get('source_id') not in {c['source_id'] for c in cited} for fact in raw_facts):
                raise ValueError('Assessment facts need attached sources.')
            strength = raw.get('strength', 'needs_evidence')
            if strength not in STRENGTHS:
                strength = 'needs_evidence'
            item = {'kind': raw['kind'], 'fields': list(dict.fromkeys(keys)), 'outcome': raw['outcome'],
                    'recommendation': _text(raw, 'recommendation', 350), 'rationale': _text(raw, 'rationale', 1200),
                    'strength': strength, 'strength_reason': _text(raw, 'strength_reason', 500),
                    'evidence': cited, 'reported_facts': facts, 'edition_relationship': 'unknown'}
            if item['outcome'] == 'change' and not any(p.get('field') in keys for p in suggestions):
                item.update(outcome='unresolved', strength='needs_evidence', recommendation='Keep the current information until a supported change is available.')
            if not cited:
                item.update(strength='needs_evidence', recommendation='Keep the current information for now.',
                            rationale='This review did not establish evidence for a change.', strength_reason='No supporting source was established.')
            if raw['kind'] == 'edition':
                compared = comparison(context, facts, evidence, raw.get('edition_relationship', 'unknown'))
                if not compared:
                    continue
                item.update(comparison=compared, edition_relationship=compared['relationship'], outcome='keep',
                            recommendation='Keep the recorded ISBN for now.', scope='book', target_id=context['target'].get('work_id', context['target']['id']))
                if compared['relationship'] == 'related_format':
                    item.update(strength='likely', rationale='The evidence connects these records as different formats of the same publication. The different ISBN alone does not require a correction.',
                                strength_reason='A source connects the identifiers and identifies different formats; complete texts have not been compared.')
                elif compared['relationship'] == 'unknown':
                    item.update(strength='needs_evidence', rationale='Different ISBNs do not by themselves establish a changed edition. The relationship still needs evidence.',
                                strength_reason='The records have not yet been reliably connected.')
            identity = [item.get('target_id', context['target']['id']), item['kind'], sorted(keys), item.get('comparison', {}).get('recorded_isbn'), item.get('comparison', {}).get('compared_isbn')]
            item['id'] = 'assessment_' + hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:24]
            accepted.append(item)
        except (ValueError, TypeError, KeyError):
            continue
    return accepted


def local_edition_fallback(context, evidence):
    """Keep a real identifier discrepancy inspectable even if AI omits a card."""
    from .review_ai import _identifiers
    recorded = isbn(_identifiers(context).get('isbn'))
    found = local_isbns(evidence)
    if not recorded or not any(fact['value'] != recorded for fact in found):
        return []
    source_map = {source['id']: source for source in evidence}
    references = []
    for fact in found[:4]:
        source = source_map[fact['source_id']]
        match = re.search(r'\bISBN[^\n]{0,100}', source['text'], re.I)
        if match:
            references.append({'source_id': source['id'], 'quote': match.group(0), 'summary': ''})
    attached = {reference['source_id'] for reference in references}
    raw = {'kind': 'edition', 'fields': [], 'outcome': 'keep',
           'recommendation': 'Keep the recorded ISBN for now.',
           'rationale': 'The copy prints a different ISBN. Compare the publication records before changing it.',
           'strength': 'needs_evidence', 'strength_reason': 'The source identifies another ISBN but does not by itself explain the relationship.',
           'evidence': references, 'reported_facts': [fact for fact in found if fact['source_id'] in attached],
           'edition_relationship': 'unknown'}
    return validate_assessments({'assessments': [raw]}, context, evidence)
