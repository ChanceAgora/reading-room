"""Read-only, bounded form suggestions from the existing library metadata.

The per-library snapshot is invalidated by published index generations and durable
metadata changes. Keystrokes never scan original books or repeat a passage scan.
Suggestions are existing values, not claims that a proposed attribution is verified.
"""
from __future__ import annotations

from collections import OrderedDict
import json
from pathlib import Path
import re
import sqlite3
from threading import RLock
import unicodedata

from .citations import _display
from .defaults import TAXONOMY
from .service import FACETS
from .storage import jsonl, read_json

KINDS = frozenset(FACETS | {
    'books', 'catalog', 'authors', 'taxonomy', 'publishers', 'translations',
    'translation_short', 'formats', 'destinations',
})
_CACHE = OrderedDict()
_LOCK = RLock()


def _key(value):
    return ' '.join(''.join(c for c in unicodedata.normalize('NFKD', value).casefold()
                            if not unicodedata.combining(c)).replace('-', ' ').split())


def _identity(value):
    """Match vocabulary names without erasing meaningful spelling differences."""
    return unicodedata.normalize('NFKC', value).casefold()


def _text(value):
    return value.strip() if isinstance(value, str) else ''


def _stamp(path):
    try:
        stat = path.stat()
        return stat.st_mtime_ns, stat.st_size, stat.st_ino
    except FileNotFoundError:
        return None


def _signature(lib):
    active = lib._active()
    database = lib.state / 'generations' / active.get('database', 'missing')
    return (active.get('generation'), active.get('database'), _stamp(database),
            *(_stamp(lib.state / filename) for filename in
              ('taxonomy.json', 'curation.jsonl', 'usage.jsonl')))


def _person_name(value):
    name = _display(value) if isinstance(value, dict) else _text(value)
    if not name or len(name) > 2000:
        return ''
    if re.search(r'\b(unverified|unknown|anonymous|no (?:named |individual )?(?:author|byline))\b', name, re.I):
        return ''
    if re.match(r'^(?:Scripture|Commentary|Translation note|Editorial|Reference)\s*[:—]', name, re.I):
        return ''
    return name


def _build(lib):
    pools = {kind: {} for kind in KINDS}

    def add(kind, value, label=None, detail='', aliases=()):
        value = _text(value); label = _text(label) or value
        if not value or not label:
            return
        # A forgiving search key is not an option identity. Exact facet filters
        # distinguish art-history from art history, and printed names can differ
        # only by a diacritic. Retain each distinct submitted value.
        key = value
        option = pools[kind].get(key)
        searchable = [_text(a) for a in aliases if _text(a)]
        if option:
            option['_search'].update(_key(a) for a in searchable)
            return
        pools[kind][key] = {
            'value': value, 'label': label, 'detail': _text(detail)[:500],
            '_search': {_key(value), _key(label), *(_key(a) for a in searchable)},
        }

    vocabulary = read_json(lib.state / 'taxonomy.json', TAXONOMY)
    terms = vocabulary.get('terms', []) if isinstance(vocabulary, dict) else []
    term_lookup = {}
    for term in terms:
        if not isinstance(term, dict):
            continue
        label = _text(term.get('label')) or _text(term.get('id'))
        aliases = [term.get('id', ''), *term.get('aliases', [])]
        if not label:
            continue
        add('taxonomy', label, detail='Vocabulary term', aliases=aliases)
        pools['taxonomy'][label]['_exclude'] = {_identity(label), *(_identity(a) for a in aliases if isinstance(a, str))}
        for name in [label, *aliases]:
            if isinstance(name, str): term_lookup[_identity(name)] = term

    # Effective curation resolves field-wise edits and respects user corrections.
    # This also makes saved bibliography changes appear before an index refresh.
    _, edits = lib._effective({'works': {}})
    works = {}; section_sources = []; target_works = {}
    facets = []
    try:
        with lib._db() as db:
            for row in db.execute("SELECT id,title,author,data FROM works WHERE coalesce(json_extract(data,'$.available'),1) != 0"):
                work = json.loads(row['data'])
                work.update(id=row['id'], title=row['title'], author=row['author'])
                works[row['id']] = work
                target_works[row['id']] = row['id']
            facets = db.execute("SELECT DISTINCT f.facet,f.value FROM facets f JOIN works w ON w.id=f.work_id WHERE coalesce(json_extract(w.data,'$.available'),1) != 0 ORDER BY f.facet,f.value COLLATE NOCASE,f.value").fetchall()
            # Read only contributor metadata, not entire extracted passage bodies.
            for row in db.execute("SELECT s.id,s.work_id,json_extract(s.data,'$.source_bibliography') AS bibliography FROM sections s JOIN works w ON w.id=s.work_id WHERE coalesce(json_extract(w.data,'$.available'),1) != 0 AND json_extract(s.data,'$.source_bibliography') IS NOT NULL"):
                section_sources.append((row['id'], row['work_id'], json.loads(row['bibliography'])))
                target_works[row['id']] = row['work_id']
            wanted = sorted({target for target, field in edits if field in ('bibliography', 'attribution', 'segments', 'profile')} - target_works.keys())
            for offset in range(0, len(wanted), 500):
                batch = wanted[offset:offset + 500]
                placeholders = ','.join('?' * len(batch))
                for table in ('sections', 'passages'):
                    for row in db.execute(f'SELECT id,work_id FROM {table} WHERE id IN ({placeholders})', batch):
                        if row['work_id'] in works:
                            target_works[row['id']] = row['work_id']
    except (ValueError, sqlite3.OperationalError):
        # The durable vocabulary and usage history are still useful before sync.
        pass

    for row in facets:
        if row['facet'] not in FACETS:
            continue
        value = _text(row['value']); term = term_lookup.get(_identity(value), {})
        label = _text(term.get('label'))
        add(row['facet'], value, detail=label if label and label != value else row['facet'].replace('_', ' ').capitalize(),
            aliases=[term.get('id', ''), label, *term.get('aliases', [])])

    def people(record, detail):
        found = False
        for role in ('authors', 'editors', 'translators'):
            for person in record.get(role) or []:
                name = _person_name(person)
                if name:
                    add('authors', name, detail=f'{role[:-1].capitalize()} · {detail}')
                    found = True
        return found

    def bibliography(record, detail):
        if not isinstance(record, dict):
            return False
        named = people(record, detail)
        for kind, field in [('publishers', 'publisher'), ('translations', 'bible_translation'),
                            ('translation_short', 'bible_translation_short'), ('formats', 'format')]:
            add(kind, record.get(field), detail=detail)
        return named

    for wid, work in works.items():
        title = _text(work.get('title')); author = _text(work.get('author'))
        record = {**work.get('bibliography', {}), **edits.get((wid, 'bibliography'), {}).get('value', {})}
        creators = [(role, name) for role in ('authors', 'editors', 'translators')
                    for person in record.get(role) or [] if (name := _person_name(person))]
        aliases = [author, *(name for _, name in creators)]
        add('books', wid, title, author, aliases=aliases)
        # Catalog q is bounded to 300 characters. Keep the full label for review,
        # but submit a searchable prefix for unusually long catalog titles.
        add('catalog', title[:300], title, detail=author, aliases=aliases)
        # Only book-level creators belong in catalog search. Chapter/passages
        # continue to appear in the separate author/contributor suggestions.
        for role, name in creators:
            add('catalog', name[:300], name, detail=f'{role[:-1].capitalize()} · {title}')
        if _person_name(author):
            add('catalog', author[:300], author, detail='Catalog creator credit')
        named = bibliography(record, title)
        if not named:
            for person in work.get('contributors', []):
                name = _person_name(person.get('name'))
                if name:
                    add('authors', name, detail=f"Catalog {person.get('role', 'contributor')} credit · {title}")
                    named = True
            if not named and _person_name(author):
                add('authors', author, detail='Catalog credit · ' + title)
        metadata = work.get('metadata', {})
        for kind, field in [('publishers', 'publisher'), ('formats', 'format')]:
            if field not in record:
                add(kind, metadata.get(field), detail='Catalog value · ' + title)

    for sid, wid, source in section_sources:
        source_record = source.get('value', {})
        correction = edits.get((sid, 'bibliography'), {})
        record = {**source_record, **correction.get('value', {})}
        # Confirmed source bylines are useful even without a manually entered name.
        if source.get('status') == 'confirmed':
            bibliography(record, 'Contribution in ' + works[wid]['title'])

    for (target, field), event in edits.items():
        wid = target_works.get(target)
        if not wid:
            continue
        detail = 'Contribution in ' + works[wid]['title']
        if field == 'bibliography' and target != wid:
            # Per-field confirmation, rather than the latest field's status.
            value = event.get('value', {})
            confirmed = {key: val for key, val in value.items()
                         if event.get('field_events', {}).get(key, event).get('status') == 'confirmed'}
            bibliography(confirmed, detail)
        elif field == 'attribution' and event.get('status') == 'confirmed':
            name = _person_name(event.get('value'))
            # Compound display strings cannot safely become individual people.
            if name and ';' not in name:
                add('authors', name, detail='Verified display credit · ' + works[wid]['title'])
        elif field == 'segments' and event.get('status') == 'confirmed':
            value = event.get('value', {})
            segments = value.get('segments', []) if isinstance(value, dict) else value if isinstance(value, list) else []
            for segment in segments:
                if isinstance(segment, dict): bibliography(segment.get('bibliography', {}), detail)

    for event in jsonl(lib.state / 'usage.jsonl'):
        for field in ('destination', 'project'):
            add('destinations', event.get(field), detail='Previous research destination')

    return {kind: tuple(sorted(options.values(), key=lambda item: (_key(item['label']), item['label'], item['value'])))
            for kind, options in pools.items()}


def _snapshot(lib):
    key = str(Path(lib.state).resolve())
    with _LOCK:
        signature = _signature(lib)
        cached = _CACHE.get(key)
        if cached and cached[0] == signature:
            _CACHE.move_to_end(key)
            return cached[1]
        result = _build(lib)
        # Do not retain a snapshot assembled while a new generation was published.
        if _signature(lib) == signature:
            _CACHE[key] = (signature, result)
            _CACHE.move_to_end(key)
            while len(_CACHE) > 8:
                _CACHE.popitem(last=False)
        return result


def suggestions(lib, kind, query='', limit=30, exclude=''):
    """Return current choices; callers may still accept a custom typed value.

    ``books`` submit stable IDs while displaying titles. ``taxonomy`` submits
    human labels accepted by the vocabulary editor. Facets preserve exact values.
    An empty query offers the first alphabetical choices; ``more`` tells the UI
    to invite narrower typing rather than implying that the list is exhaustive.
    """
    if kind not in KINDS:
        raise ValueError('That suggestion category is not supported.')
    if not isinstance(query, str) or len(query) > 300 or any(ord(c) < 32 for c in query):
        raise ValueError('Suggestion searches must be text of at most 300 characters without control characters.')
    if not isinstance(exclude, str) or len(exclude) > 300:
        raise ValueError('The excluded suggestion must be text of at most 300 characters.')
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError('Choose between 1 and 100 suggestions.')
    needle = _key(query); omitted = _identity(exclude)
    matches = []
    for option in _snapshot(lib)[kind]:
        if omitted and omitted in option.get('_exclude', {_identity(option['value'])}):
            continue
        if needle and not any(needle in text for text in option['_search']):
            continue
        matches.append(option)
    # Keep exact values/labels first, then prefix matches, then substring matches.
    if needle:
        matches.sort(key=lambda item: (0 if needle in (_key(item['value']), _key(item['label'])) else
                                      1 if _key(item['label']).startswith(needle) else 2,
                                      _key(item['label']), item['label']))
    return {'options': [{key: option[key] for key in ('value', 'label', 'detail')} for option in matches[:limit]],
            'total': len(matches), 'more': len(matches) > limit}
