"""Durable, editable vocabulary and bounded views of overlapping classifications."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import re
import sqlite3
import unicodedata

from .defaults import TAXONOMY
from .storage import atomic_json, now, read_json, writer

RELATIONS = ('broader', 'narrower', 'related')


def _key(value):
    return ' '.join(unicodedata.normalize('NFKC', value).casefold().replace('-', ' ').split())


def term_id(label):
    """Generate a portable stable identifier without making readers invent one."""
    text = ''.join(c for c in unicodedata.normalize('NFKD', label) if not unicodedata.combining(c))
    slug = re.sub('[^a-z0-9]+', '-', text.casefold()).strip('-')[:80].rstrip('-')
    return slug or 'term-' + hashlib.sha256(label.encode()).hexdigest()[:12]


def _string(value, field, maximum):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f'{field} must be a nonempty text value of at most {maximum} characters.')
    if any(ord(c) < 32 and c not in '\n\t' for c in value):
        raise ValueError(f'{field} contains an unsupported control character.')
    return value.strip()


def _strings(value, field):
    if not isinstance(value, list) or len(value) > 50:
        raise ValueError(f'{field} must contain no more than 50 text values.')
    result = []
    keys = set()
    for item in value:
        item = _string(item, field, 160)
        if _key(item) in keys:
            raise ValueError(f'{field} contains a duplicate value.')
        keys.add(_key(item)); result.append(item)
    return result


def _vocabulary(lib):
    data = read_json(lib.state / 'taxonomy.json', deepcopy(TAXONOMY))
    if not isinstance(data, dict) or not isinstance(data.get('terms'), list):
        raise ValueError('The vocabulary record needs repair before it can be edited.')
    return data


def list_taxonomy(lib, query='', offset=0, limit=100):
    """Use the existing index only; no source files are opened to browse facets."""
    if not isinstance(query, str) or len(query) > 300:
        raise ValueError('Vocabulary searches must be 300 characters or fewer.')
    offset = max(0, int(offset)); limit = max(1, min(int(limit), 200))
    data = _vocabulary(lib); needle = _key(query)
    terms = sorted(data['terms'], key=lambda t: _key(t.get('label', t['id'])))
    lookup = {}
    for term in terms:
        for label in [term['id'], term.get('label', term['id'])] + term.get('aliases', []):
            lookup[_key(label)] = term
    facets = []; warning = None
    try:
        with lib._db() as db:
            rows = db.execute("SELECT f.facet,f.value,count(DISTINCT f.work_id) AS work_count FROM facets f JOIN works w ON w.id=f.work_id WHERE coalesce(json_extract(w.data,'$.available'),1) != 0 GROUP BY f.facet,f.value ORDER BY f.facet,f.value COLLATE NOCASE").fetchall()
            for row in rows:
                term = lookup.get(_key(row['value']))
                item = {'facet': row['facet'], 'value': row['value'], 'label': term.get('label', row['value']) if term else row['value'], 'work_count': row['work_count'], 'term_id': term['id'] if term else None}
                if not needle or needle in _key(item['label'] + ' ' + item['value'] + ' ' + item['facet']): facets.append(item)
    except (ValueError, sqlite3.OperationalError):
        warning = 'The vocabulary is available. Classification counts will appear after the library index is synchronized.'
    filtered = [t for t in terms if not needle or needle in _key(' '.join([t['id'], t.get('label', ''), *t.get('aliases', [])]))]
    return {'terms': [{k: v for k, v in t.items() if k not in ('history', 'relationship_history')} for t in filtered[offset:offset + limit]], 'facets': facets[offset:offset + limit], 'term_count': len(terms), 'matching_term_count': len(filtered), 'matching_facet_count': len(facets), 'query': query, 'offset': offset, 'limit': limit, 'has_more': offset + limit < max(len(filtered), len(facets)), 'warning': warning}


def get_term(lib, id):
    data = _vocabulary(lib)
    return next((deepcopy(t) for t in data['terms'] if t['id'] == id), None)


def _validate_hierarchy(terms):
    parents = {t['id']: set(t.get('broader', [])) for t in terms}
    def visit(id, active, complete):
        if id in active: raise ValueError('Broader and narrower terms cannot form a circular hierarchy. Use a related term for a lateral connection.')
        if id in complete: return
        active.add(id)
        for parent in parents.get(id, []): visit(parent, active, complete)
        active.remove(id); complete.add(id)
    complete = set()
    for id in parents: visit(id, set(), complete)


def save_term(lib, id, data):
    """Preserve curation, record evidence, and keep relationship inverses consistent."""
    if not isinstance(id, str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,79}', id):
        raise ValueError('The vocabulary identifier must use lowercase letters, digits, and hyphens.')
    if not isinstance(data, dict): raise ValueError('A vocabulary term must be an object.')
    label = _string(data.get('label'), 'Name', 160)
    evidence = _string(data.get('evidence'), 'Evidence or editorial reason', 4000)
    origin = data.get('origin', 'user'); status = data.get('status', 'confirmed')
    if origin not in ('user', 'codex', 'import') or status not in ('provisional', 'confirmed', 'disputed'):
        raise ValueError('The vocabulary origin or review status is not recognized.')
    with writer(lib.state):
        vocabulary = _vocabulary(lib); terms = deepcopy(vocabulary['terms'])
        old = next((t for t in terms if t['id'] == id), None)
        if old and data.get('create_only'):
            raise ValueError('That vocabulary term already exists. Open its entry to edit it.')
        if old and old.get('origin') == 'user' and origin != 'user':
            raise ValueError('This term has a user correction; generated metadata cannot replace it.')
        aliases = _strings(data.get('aliases', old.get('aliases', []) if old else []), 'Aliases')
        names = {_key(id), _key(label)}
        for alias in aliases:
            if _key(alias) in names: raise ValueError('An alias repeats the term’s name or identifier.')
            names.add(_key(alias))
        lookup = {}
        for term in terms:
            if term['id'] == id: continue
            for name in [term['id'], term.get('label', term['id'])] + term.get('aliases', []):
                key = _key(name)
                if key in names: raise ValueError('That name or alias already belongs to another vocabulary term: ' + term.get('label', term['id']))
                lookup[key] = term['id']
        relations = {}
        for field in RELATIONS:
            values = _strings(data.get(field, old.get(field, []) if old else []), field.capitalize())
            resolved = []
            for value in values:
                if _key(value) in names: raise ValueError('A term cannot be related to itself.')
                target = lookup.get(_key(value))
                if not target: raise ValueError('Create the vocabulary term “' + value + '” first, then add this relationship.')
                if target in resolved: raise ValueError('Two relationship names refer to the same term.')
                resolved.append(target)
            relations[field] = resolved
        if set(relations['broader']) & set(relations['narrower']):
            raise ValueError('A term cannot be both broader and narrower than the same term.')
        stamp = now()
        record = {**(old or {}), 'id': id, 'label': label, 'aliases': aliases, **relations, 'origin': origin, 'status': status, 'evidence': evidence, 'updated_at': stamp}
        record.setdefault('created_at', stamp)
        history = list(record.get('history', []))
        if old: history.append({k: deepcopy(v) for k, v in old.items() if k != 'history'})
        record['history'] = history
        if old: terms[terms.index(old)] = record
        else: terms.append(record)
        inverse = {'broader': 'narrower', 'narrower': 'broader', 'related': 'related'}
        for field, reverse in inverse.items():
            old_targets = set((old or {}).get(field, [])); new_targets = set(relations[field])
            for term in terms:
                if term['id'] == id: continue
                changed = term['id'] in old_targets ^ new_targets
                if changed and term.get('origin') == 'user' and origin != 'user':
                    raise ValueError('This relationship would change a user-corrected term; generated metadata cannot replace it.')
                if term['id'] in old_targets - new_targets:
                    term[reverse] = [v for v in term.get(reverse, []) if v != id]
                    term.setdefault('relationship_history', []).append({'term_id': id, 'relationship': reverse, 'action': 'removed', 'origin': origin, 'status': status, 'evidence': evidence, 'created_at': stamp})
                if term['id'] in new_targets and id not in term.get(reverse, []):
                    term.setdefault(reverse, []).append(id)
                    term.setdefault('relationship_history', []).append({'term_id': id, 'relationship': reverse, 'action': 'added', 'origin': origin, 'status': status, 'evidence': evidence, 'created_at': stamp})
        _validate_hierarchy(terms)
        vocabulary.update(terms=terms, updated_at=stamp)
        atomic_json(lib.state / 'taxonomy.json', vocabulary)
        return {**{k: deepcopy(v) for k, v in record.items() if k not in ('history', 'relationship_history')}, 'history_count': len(record['history'])}


def facet_books(lib, facet, value, offset=0, limit=50, sort='title'):
    from .service import FACETS
    from .catalog import page
    if facet not in FACETS: raise ValueError('That classification is not supported.')
    value = _string(value, 'Classification value', 200)
    offset = max(0, int(offset)); limit = max(1, min(int(limit), 100))
    import json
    with lib._db() as db:
        clause = "FROM works w WHERE coalesce(json_extract(w.data,'$.available'),1) != 0 AND EXISTS (SELECT 1 FROM facets f WHERE f.work_id=w.id AND f.facet=? AND f.value=? COLLATE NOCASE)"
        rows = db.execute('SELECT w.data ' + clause, (facet, value)).fetchall()
    books = [json.loads(row['data']) for row in rows]
    result = page(books, sort=sort, offset=offset, limit=limit)
    for book in result['books']:
        book['file_count'] = len(book.get('files', []))
    return {'facet': facet, 'value': value, **result}
