"""Bounded, source-grounded Chicago 18 notes/bibliography for local passages.

Rules: https://www.chicagomanualofstyle.org/tools_citationguide/citation-guide-1.html
SMU context: https://guides.smu.edu/theologycitations/home and
https://guides.smu.edu/chicagonb . Instructors may require Turabian or SBL instead.

``bibliography`` annotations are field-wise patches on works or sections:
  title, short_title, authors/editors/translators, publisher, year, edition,
  volume, volume_title, url, doi, format, type, locator.
Names are [{"given":"Jane","family":"Doe"}] or
[{"literal":"Liu Xinwu","short":"Liu"}] (no automatic cultural inversion).
Section type is chapter/poem/entry; title is the contribution's title. Work
publication data supplies its container. A confirmed annotation with evidence
verifies its provided fields. Catalog values remain labeled as candidates.
Null authors mean unknown; a confirmed empty list means no named author.
Null section translators inherit the volume; an empty list explicitly overrides
that credit with no named translator for the contribution.

Locator overrides: {"type":"page|chapter|section|paragraph|verse", "value":"…",
"verified":true, "evidence":"…"}. Plain strings are unverified candidates.
No original archives are opened, AI called, or bibliographic facts invented.
"""
from __future__ import annotations

import copy
import hashlib
import html
import json
import re
from pathlib import Path
from urllib.parse import urlparse
from .local_server import local_base_url

STYLE = 'chicago-18-notes-bibliography'
STYLE_NAME = 'Chicago Manual of Style, 18th edition — notes and bibliography'
RULE_URLS = [
    'https://www.chicagomanualofstyle.org/tools_citationguide/citation-guide-1.html',
    'https://guides.smu.edu/chicagonb',
    'https://guides.smu.edu/theologycitations/home',
]
SCHEMA = {
    'text_fields': ['title', 'short_title', 'publisher', 'year', 'edition', 'volume', 'volume_title', 'url', 'doi', 'format', 'bible_translation', 'bible_translation_short'],
    'name_fields': ['authors', 'editors', 'translators'],
    'name_examples': [{'given': 'Jane', 'family': 'Doe'}, {'literal': 'Liu Xinwu', 'short': 'Liu'}],
    'types': ['book', 'chapter', 'poem', 'entry', 'scripture'],
    'scripture_scopes': ['text_only', 'mixed'],
    'locator_types': ['page', 'chapter', 'section', 'paragraph', 'verse'],
    'verification': 'Use a confirmed bibliography annotation with source evidence. Unknown fields stay unknown.',
}
_FIELDS = set(SCHEMA['text_fields'] + SCHEMA['name_fields'] + ['type', 'locator', 'scripture_scope'])
_NAME_FIELDS = set(SCHEMA['name_fields'])
_LOCATOR_TYPES = set(SCHEMA['locator_types'])
_BAD_HEADINGS = re.compile(r'^(?:front matter|(?:table of )?contents|list of (?:figures|illustrations|tables)|index|untitled)$', re.I)


def _text(value, limit=2000):
    return re.sub(r'\s+', ' ', str(value or '')).strip()[:limit]


def _url(value):
    value = _text(value)
    parsed = urlparse(value)
    return value if parsed.scheme in ('http', 'https') and parsed.netloc and not parsed.username and not parsed.password else None


def validate_locator(value):
    if isinstance(value, str):
        if not value.strip() or len(value) > 500:
            raise ValueError('Locator text must be 1–500 characters.')
        return
    if not isinstance(value, dict) or set(value) - {'type', 'value', 'verified', 'evidence'}:
        raise ValueError('Locator must contain type, value, and optional verified/evidence fields.')
    if value.get('type') not in _LOCATOR_TYPES or not isinstance(value.get('value'), str) or not value['value'].strip() or len(value['value']) > 500:
        raise ValueError('Choose a supported locator type and 1–500 characters of source locator text.')
    if 'verified' in value and not isinstance(value['verified'], bool):
        raise ValueError('Locator verified must be true or false.')
    if value.get('evidence') is not None and (not isinstance(value['evidence'], str) or len(value['evidence']) > 4000):
        raise ValueError('Locator evidence must be text of at most 4000 characters.')
    if value.get('verified') and not _text(value.get('evidence')):
        raise ValueError('A verified locator requires source evidence.')
    if value.get('type') == 'page' and re.search(r'\b(block|paragraph|position|location|offset|rendered)\b', value['value'], re.I):
        raise ValueError('Extraction and layout positions cannot be used as printed page numbers.')


def validate_bibliography(value):
    """Reject malformed/oversized curation before it reaches the durable log."""
    if not isinstance(value, dict) or set(value) - _FIELDS:
        raise ValueError('Bibliography must be an object using the supported citation fields.')
    if len(json.dumps(value, ensure_ascii=False)) > 30000:
        raise ValueError('Bibliography metadata exceeds the 30,000-character limit.')
    for key, item in value.items():
        if item is None:  # Explicitly clear an incorrect field without inventing a replacement.
            continue
        if key in _NAME_FIELDS:
            if not isinstance(item, list) or len(item) > 50:
                raise ValueError(key + ' must be a list of at most 50 structured names.')
            for person in item:
                if not isinstance(person, dict) or set(person) - {'given', 'family', 'literal', 'short', 'suffix'}:
                    raise ValueError('Names require given/family or literal, with optional short/suffix.')
                if any(not isinstance(v, str) or len(v) > 500 for v in person.values()):
                    raise ValueError('Name components must be strings of at most 500 characters.')
                literal = _text(person.get('literal'))
                if literal and (_text(person.get('given')) or _text(person.get('family'))):
                    raise ValueError('Use either literal or given/family for a name, not both.')
                if not literal and not _text(person.get('family')):
                    raise ValueError('A name needs literal or family; given alone is ambiguous.')
        elif key == 'locator':
            validate_locator(item)
        elif key == 'type':
            if item not in SCHEMA['types']:
                raise ValueError('Citation type must be book, chapter, poem, entry, or scripture.')
        elif key == 'scripture_scope':
            if item not in SCHEMA['scripture_scopes']:
                raise ValueError('Scripture scope must be text_only or mixed.')
        elif key == 'year':
            if isinstance(item, bool) or not isinstance(item, (str, int)) or len(str(item)) > 40:
                raise ValueError('Publication year must be a short string or integer.')
        elif not isinstance(item, str) or len(item) > 2000:
            raise ValueError(key + ' must be text of at most 2000 characters.')
        if key == 'url' and item and not _url(item):
            raise ValueError('Citation URL must be an HTTP or HTTPS URL without embedded credentials.')
        if key == 'doi' and item and not re.fullmatch(r'(?:https://doi\.org/)?10\.\d{4,9}/\S+', item):
            raise ValueError('Use a DOI beginning with 10. or https://doi.org/.')


def _display(person):
    if person.get('literal'):
        return _text(person['literal'])
    parts = [_text(person.get('given')), _text(person.get('family'))]
    name = ' '.join(p for p in parts if p)
    return name + (', ' + _text(person['suffix']) if person.get('suffix') else '')


def _inverted(person):
    if person.get('literal'):
        return _display(person)
    name = _text(person.get('family'))
    if person.get('given'):
        name += ', ' + _text(person['given'])
    if person.get('suffix'):
        name += ', ' + _text(person['suffix'])
    return name


def _short_name(person):
    return _text(person.get('short') or person.get('family') or person.get('literal'))


def _join_names(people, mode='note'):
    if not people:
        return ''
    # CMOS 18, 13.23: bibliography lists up to six names (first three + et al.
    # beyond six). Credits after "edited/translated by" keep natural order;
    # only the first name at the entry's head is inverted. See the official
    # quick guide's chapter example and help-tools/what-s-new.html.
    bibliography = mode in ('bibliography', 'bibliography_inline')
    if mode in ('note', 'short') and len(people) > 2:
        return (_short_name(people[0]) if mode == 'short' else _display(people[0])) + ' et al.'
    shown = people[:3] if bibliography and len(people) > 6 else people
    names = [(_inverted(p) if i == 0 else _display(p)) if mode == 'bibliography' else _short_name(p) if mode == 'short' else _display(p) for i, p in enumerate(shown)]
    if bibliography and len(people) > 6:
        return ', '.join(names) + ', et al.'
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return names[0] + (', and ' if mode == 'bibliography' else ' and ') + names[1]
    return ', '.join(names[:-1]) + ', and ' + names[-1]


def _name_candidates(work, role):
    meta = work.get('metadata', {})
    # Explicit acquisition roles remain candidates, with supplied name structure
    # preserved. A combined display credit does not establish any of these roles.
    key = {'author': 'authors', 'editor': 'editors', 'translator': 'translators'}.get(role)
    if key and isinstance(meta.get(key), list):
        return [copy.deepcopy(n) if isinstance(n, dict) else {'literal': _text(n)} for n in meta[key]
                if isinstance(n, dict) and _display(n) or not isinstance(n, dict) and _text(n)][:50]
    return [{'literal': _text(p['name'])} for p in work.get('contributors', []) if p.get('role') == role and _text(p.get('name')) and _text(p.get('name')).lower() != 'unknown'][:50]


def _annotation(edits, target, derived=None):
    """Source bylines supply a base; durable corrections win field by field."""
    event = copy.deepcopy(derived or {})
    curated = edits.get((target, 'bibliography'), {})
    if not event:
        return curated, copy.deepcopy(curated.get('value', {}))
    event.setdefault('field_events', {})
    for field in event.get('value', {}):
        event['field_events'].setdefault(field, {key: value for key, value in event.items() if key not in ('value', 'field_events')})
    for field, value in curated.get('value', {}).items():
        event.setdefault('value', {})[field] = copy.deepcopy(value)
        event['field_events'][field] = copy.deepcopy(curated.get('field_events', {}).get(field, curated))
    return event, copy.deepcopy(event.get('value', {}))


def _verified(event, field):
    origin = event.get('field_events', {}).get(field, event)
    return origin.get('status') == 'confirmed' and bool(origin.get('evidence'))


def _provenance(event, field, fallback=None):
    source = event.get('field_events', {}).get(field, event)
    if field in event.get('value', {}):
        return {'origin': source.get('origin', 'curation'), 'status': source.get('status', 'provisional'), 'evidence': _text(source.get('evidence'), 4000), 'annotation_id': source.get('id'), 'target_id': source.get('target_id')}
    return {'origin': 'acquisition_catalog', 'status': 'candidate', 'evidence': _text(fallback, 4000)}


def _locator(lib, row, block_rows, section, override, warnings):
    if override is not None:
        validate_locator(override)
        if isinstance(override, str):
            return {'type': 'section', 'value': _text(override, 500), 'verified': False, 'origin': 'supplied_override', 'evidence': '', 'display': _text(override, 500)}
        result = {**override, 'value': _text(override['value'], 500), 'origin': 'supplied_override'}
        labels = {'page': '', 'chapter': 'chap. ', 'section': 'sec. ', 'paragraph': 'para. ', 'verse': ''}
        result['display'] = labels[result['type']] + result['value']
        return result
    pages = []
    for raw in block_rows:
        block = json.loads(raw['data'])
        # A terminal marker announces the next page but is not content on it.
        # Following text/image blocks inherit its label and count normally.
        if block.get('kind') == 'pagebreak':
            continue
        # extractor v2 locator.page means an explicit EPUB marker, never Word layout.
        if Path(block.get('path', '')).suffix.lower() == '.epub' and block.get('locator', {}).get('page'):
            page = _text(block['locator']['page'], 100)
            if page not in pages:
                pages.append(page)
    if pages:
        if all(p.isdecimal() for p in pages) and [int(p) for p in pages] == sorted(int(p) for p in pages):
            value = pages[0] if len(pages) == 1 else pages[0] + '–' + pages[-1]
        else:
            value = ', '.join(pages[:20])
        return {'type': 'page', 'value': value, 'display': value, 'verified': True, 'origin': 'source_page_markers', 'evidence': 'Explicit EPUB page labels attached to the selected passage; not reflow or extraction ordinals.', 'source_labels': pages[:20]}
    heading = _text(section.get('title'), 500)
    if heading and not _BAD_HEADINGS.fullmatch(heading) and len(heading) < 300:
        warnings.append('No fixed page marker is available. This citation uses the indexed section heading; verify that heading in the source before submission.')
        return {'type': 'section', 'value': heading, 'display': 'sec. “' + heading + '”', 'verified': False, 'origin': 'indexed_heading', 'evidence': 'Source-derived heading; may be provisional or broader than the quoted passage.'}
    warnings.append('No reliable page or section locator is recorded. Extraction blocks and Word layout pages are not scholarly page numbers.')
    return {'type': None, 'value': None, 'display': '', 'verified': False, 'origin': 'unavailable', 'evidence': ''}


def _sentence(text):
    return text.rstrip(' .') + '.'


def _render(data, mode='plain'):
    def escape(value):
        value = str(value)
        if mode == 'html':
            return html.escape(value)
        if mode == 'markdown':
            return re.sub(r'([\\`*_\[\]<>])', r'\\\1', value)
        return value
    def title(value):
        value = escape(value)
        return '<i>' + value + '</i>' if mode == 'html' else '*' + value + '*' if mode == 'markdown' else value
    def quoted(value):
        return '“' + escape(value).replace('“', '‘').replace('”', '’') + '”'
    if data['type'] == 'scripture':
        reference = escape(data['locator']['value'] or '[biblical reference unverified]')
        translation = escape(data.get('bible_translation') or '[translation unverified]')
        short_translation = escape(data.get('bible_translation_short') or data.get('bible_translation') or '[translation unverified]')
        return {'full_note': _sentence(reference + ' (' + translation + ')'),
                'short_note': _sentence(reference + ' (' + short_translation + ')'),
                'bibliography': ''}
    authors = data['authors']; editors = data['editors']; translators = data['translators']
    creator_role = ''
    creators = authors
    if not creators and data['type'] == 'book':
        if editors:
            creators = editors; creator_role = 'eds.' if len(editors) > 1 else 'ed.'
        elif translators:
            creators = translators; creator_role = 'trans.'
    lead = escape(_join_names(creators))
    bib_lead = escape(_join_names(creators, 'bibliography'))
    short_lead = escape(_join_names(creators, 'short'))
    if creator_role:
        lead += ', ' + creator_role; bib_lead += ', ' + creator_role
    if data['type'] != 'book':
        note = (lead + ', ' if lead else '') + quoted(data['contribution_title']) + ', in ' + title(data['title'])
        short = (short_lead + ', ' if short_lead else '') + quoted(data['contribution_short_title'])
        bib = (_sentence(bib_lead) + ' ' if bib_lead else '') + _sentence(quoted(data['contribution_title'])) + ' In ' + title(data['title'])
        if editors:
            note += ', ed. ' + escape(_join_names(editors))
            bib += ', edited by ' + escape(_join_names(editors, 'bibliography_inline'))
    else:
        note = (lead + ', ' if lead else '') + title(data['title'])
        short = (short_lead + ', ' if short_lead else '') + title(data['short_title'])
        bib = (_sentence(bib_lead) + ' ' if bib_lead else '') + title(data['title'])
        if authors and editors:
            note += ', ed. ' + escape(_join_names(editors))
            bib = _sentence(bib) + ' Edited by ' + escape(_join_names(editors, 'bibliography_inline'))
    if translators and creator_role != 'trans.':
        note += ', trans. ' + escape(_join_names(translators))
        bib = _sentence(bib) + ' Translated by ' + escape(_join_names(translators, 'bibliography_inline'))
    if data.get('edition'):
        note += ', ' + escape(data['edition'])
        bib = _sentence(bib) + ' ' + escape(data['edition'])
    if data.get('volume'):
        vol = 'vol. ' + escape(data['volume'])
        if data.get('volume_title'):
            vol += ', ' + title(data['volume_title'])
        note += ', ' + vol; bib = _sentence(bib) + ' ' + vol[0].upper() + vol[1:]
    publication = escape(data['publisher']) + ', ' + escape(data['year'])
    note += ' (' + publication + ')'
    bib = _sentence(bib) + ' ' + publication
    if data['locator']['display']:
        note += ', ' + escape(data['locator']['display'])
        short += ', ' + escape(data['locator']['display'])
    if data['access']:
        note += ', ' + escape(data['access'])
        bib = _sentence(bib) + ' ' + escape(data['access'])
    return {key: re.sub(r'”([,.])', r'\1”', _sentence(value)) for key, value in [('full_note', note), ('short_note', short), ('bibliography', bib)]}


def _cite_scripture(lib, passage_id, row, block_rows, section, work, cat,
                    event, bibliography, warnings, locator, target_id):
    """Cite Bible text by reference and version, never by a commentary author."""
    missing = []; review = []; provenance = {}
    for field in ('type', 'scripture_scope', 'bible_translation'):
        provenance['section.' + field] = _provenance(event, field)
        if not bibliography.get(field):
            missing.append('section.' + field)
        elif not _verified(event, field):
            review.append('section.' + field)
    short_translation = _text(bibliography.get('bible_translation_short'))
    if short_translation:
        provenance['section.bible_translation_short'] = _provenance(event, 'bible_translation_short')
        if not _verified(event, 'bible_translation_short'):
            review.append('section.bible_translation_short')
            short_translation = ''
    if bibliography.get('scripture_scope') != 'text_only':
        review.append('section.scripture_scope')
        warnings.append('This target is not verified as Scripture text only. Separate commentary, quotations, and translation notes before treating this as a citation of the complete passage.')
    chosen = locator if locator is not None else bibliography.get('locator')
    resolved = _locator(lib, row, block_rows[:2000], section, chosen, warnings)
    if not resolved.get('value'):
        missing.append('locator')
    if resolved.get('type') != 'verse' or not re.search(r'\S.*\s+\d+:\d+', resolved.get('value') or ''):
        review.append('locator')
        warnings.append('Scripture requires its biblical book, chapter, and verse; a page, heading, or extraction position is not sufficient.')
    if not resolved.get('verified'):
        review.append('locator')
    if locator is None:
        provenance['section.locator'] = _provenance(event, 'locator')
        if bibliography.get('locator') and not _verified(event, 'locator'):
            review.append('locator')
    if len(block_rows) > 2000:
        review.append('locator.coverage')
        warnings.append('The passage exceeds the source-block inspection limit; verify complete reference coverage.')
    meta = work.get('metadata', {})
    files = [cat['files'][fid] for fid in json.loads(row['data'])['file_ids']]
    data = {'type': 'scripture', 'title': work.get('title'),
            'authors': [], 'editors': [], 'translators': [],
            'bible_translation': _text(bibliography.get('bible_translation')),
            'bible_translation_short': short_translation,
            'scripture_scope': bibliography.get('scripture_scope'), 'locator': resolved,
            'container_title': work.get('title')}
    versions = [{'file_id': f['id'], 'sha256': f.get('sha256'), 'path': f['path']} for f in files[:20]]
    identity = {'work_id': work['id'], 'edition_id': work.get('edition_id'),
                'section_id': section['id'], 'passage_id': passage_id,
                'source_hashes': [f.get('sha256') for f in files], 'locator': resolved, 'style': STYLE}
    citation_id = 'citation_' + hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:24]
    warnings.append('Scripture is normally cited by biblical book, chapter, verse, and translation in text or notes, without a separate bibliography entry. Cite study notes and commentary separately. Course-specific instructions can override this convention.')
    return {'citation_id': citation_id, 'style': STYLE, 'style_name': STYLE_NAME, **_render(data),
            'html': _render(data, 'html'), 'markdown': _render(data, 'markdown'),
            'ready': not missing and not review, 'needs_review': bool(missing or review),
            'metadata_scope': 'passage' if target_id == passage_id else 'section',
            'contribution_target_id': target_id, 'bibliography_required': False,
            'missing_fields': list(dict.fromkeys(missing)), 'review_fields': list(dict.fromkeys(review)),
            'warnings': list(dict.fromkeys(warnings))[:30], 'locator': resolved, 'metadata': data,
            'attribution': _text(section.get('attribution'), 2000), 'provenance': provenance,
            'source_identity': {**identity, 'files': versions, 'generation': lib._active().get('generation')},
            'links': {'local_passage': local_base_url(lib) + '/read/' + passage_id,
                      'local_citation': local_base_url(lib) + '/cite/' + passage_id,
                      'source_files': [f['path'] for f in files[:20]], 'canonical': None,
                      'acquisition': _url(meta.get('source_url')), 'style_guidance': RULE_URLS + [
                          'https://guides.lib.monash.edu/chicago-18-a-notes/ancient-and-sacred-sources',
                          'https://libguides.princeton.edu/religion/citingsacredtexts']},
            'schema': SCHEMA}


def cite_passage(lib, passage_id, locator=None, segment_id=None):
    """Select a complete passage, or one explicitly bounded source component."""
    from .passage_segments import segments_for_passage, segment_conflict
    _, edits = lib._effective(lib._catalog())
    event = edits.get((passage_id, 'segments'))
    if not event:
        if segment_id:
            raise ValueError('This passage has no recorded source components.')
        return _cite_passage(lib, passage_id, locator)
    # read() performs source freshness checks before any component is cited.
    lib.read(passage_id, context=0, max_chars=500)
    with lib._db() as db:
        row = db.execute('SELECT * FROM passages WHERE id=?', (passage_id,)).fetchone()
        blocks = db.execute('SELECT data FROM blocks WHERE work_id=? AND ordinal BETWEEN ? AND ? ORDER BY ordinal', (row['work_id'], row['first_ordinal'], row['last_ordinal'])).fetchall()
    segments = segments_for_passage(passage_id, edits, blocks)
    if not segments:
        warning = segment_conflict(passage_id, edits) or 'Source components are unavailable; recheck their recorded boundaries.'
        if segment_id:
            raise ValueError('This source component is withheld. ' + warning)
        result = _cite_passage(lib, passage_id, locator)
        result['warnings'] = list(dict.fromkeys([*result['warnings'], warning]))
        result['review_fields'] = list(dict.fromkeys([*result['review_fields'], 'component.user_correction']))
        result.update(ready=False, needs_review=True)
        return result
    if segment_id:
        segment = next((item for item in segments if item['segment_id'] == segment_id), None)
        if segment is None:
            raise ValueError('Unknown source component for this passage.')
        return _component_citation(lib, passage_id, segment, locator)
    components = [_component_citation(lib, passage_id, segment) for segment in segments]
    if len(components) == 1:
        return components[0]
    result = copy.deepcopy(components[0])
    result.update(full_note='', short_note='', bibliography='',
                  html={'full_note':'','short_note':'','bibliography':''},
                  markdown={'full_note':'','short_note':'','bibliography':''},
                  ready=False, needs_review=True, metadata_scope='passage',
                  metadata={'type':'mixed','authors':[],'editors':[],'translators':[]},
                  attribution='Multiple source components; choose the text you are citing',
                  missing_fields=[], review_fields=['choose_component'],
                  component_citations=components,
                  warnings=['This passage contains separately credited material. Choose the Scripture, commentary, or other component you actually used; there is no single citation for all of it.'],
                  locator={'type':None,'value':None,'display':'','verified':False},
                  bibliography_required=False)
    result.pop('segment_id', None); result.pop('text_type', None)
    result['source_identity'].pop('segment_id', None)
    result['source_identity'].pop('source_block_ids', None)
    result['links']['local_citation'] = local_base_url(lib) + '/cite/' + passage_id
    result['citation_id'] = 'citation_' + hashlib.sha256(json.dumps(result['source_identity'], sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:24]
    return result


def _component_citation(lib, passage_id, segment, locator=None):
    result = _cite_passage(lib, passage_id, locator, _segment=segment)
    result.update(segment_id=segment['segment_id'], text_type=segment['text_type'], metadata_scope='segment')
    result['excerpt'] = '\n'.join(block.get('text','') for block in segment['blocks'])[:500]
    if segment['text_type'] == 'unknown' or 'unverified' in segment['attribution'].lower():
        result['review_fields'].append('component.attribution')
        result.update(ready=False, needs_review=True)
        result['warnings'].append('This component still has an unresolved source type or credit; inspect the recorded evidence before citing it.')
    result['source_identity'].update(segment_id=segment['segment_id'],
                                     source_block_ids=[block['id'] for block in segment['blocks']])
    result['citation_id'] = 'citation_' + hashlib.sha256(json.dumps(result['source_identity'], sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:24]
    result['links']['local_citation'] += '?segment=' + segment['segment_id']
    if segment.get('notes'):
        result['warnings'].append(segment['notes'])
    return result


def _cite_passage(lib, passage_id, locator=None, _segment=None):
    """Return a citation draft plus evidence; never convert uncertainty into fact."""
    reading = lib.read(passage_id, context=0, max_chars=500)
    cat = lib._catalog(); effective, edits = lib._effective(cat)
    passage = reading['passage']; work = effective[passage['work_id']]
    with lib._db() as db:
        row = db.execute('SELECT * FROM passages WHERE id=?', (passage_id,)).fetchone()
        section_row = db.execute('SELECT data FROM sections WHERE id=?', (row['section_id'],)).fetchone()
        block_rows = db.execute('SELECT data FROM blocks WHERE work_id=? AND ordinal BETWEEN ? AND ? ORDER BY ordinal LIMIT 2001', (row['work_id'], row['first_ordinal'], row['last_ordinal'])).fetchall()
    section = json.loads(section_row['data']); warnings = list(passage.get('limitations', []))[:20]
    work_event, wb = _annotation(edits, work['id']); section_event, sb = _annotation(edits, section['id'], section.get('source_bibliography'))
    passage_bibliography=edits.get((passage_id,'bibliography'))
    if passage_bibliography:
        section_event,sb=_annotation(edits,passage_id,section_event)
    from .passage_curation import passage_credit, credit_limitations
    credit=passage_credit(passage_id,edits)
    if credit:section['attribution']=credit['attribution']
    warnings=credit_limitations(warnings,credit)
    contribution_target_id=passage_id if passage_bibliography or credit else section['id']
    if _segment:
        # Component metadata is independent of the broader passage/section.
        # It must never inherit a neighboring scholar or a stale verse range.
        sb = copy.deepcopy(_segment['bibliography'])
        section_event = {key:value for key,value in _segment['event'].items() if key not in ('value','field_events')}
        section_event['value'] = sb
        section['attribution'] = _segment['attribution']
        block_rows = [{'data':json.dumps(block,ensure_ascii=False)} for block in _segment['blocks']]
        warnings = [warning for warning in warnings if not warning.startswith((
            'This passage contains separately credited portions.',
            'A described portion still has unresolved text type or attribution;',
            'Scripture scope requires verification;',
            'Scripture classification is provisional or disputed;',
            'Bible translation requires verification;'))]
        warnings = credit_limitations(warnings, {'attribution':_segment['attribution'], 'event':section_event})
        contribution_target_id = passage_id
    validate_bibliography(wb); validate_bibliography(sb)
    if sb.get('type') == 'scripture':
        if not credit and not _segment:
            from .passage_curation import scripture_credit
            scripture = scripture_credit(sb, section_event)
            section['attribution'] = scripture['attribution']
            warnings = credit_limitations(warnings, scripture)
        return _cite_scripture(lib, passage_id, row, block_rows, section, work, cat,
                               section_event, sb, warnings, locator, contribution_target_id)
    meta = work.get('metadata', {}); provenance = {}; missing = []; review = []
    def field(name, fallback=None, required=False):
        value = wb[name] if name in wb else fallback
        provenance[name] = _provenance(work_event, name, meta.get('edition_verification'))
        if required and not value:
            missing.append(name)
        elif value and not _verified(work_event, name):
            review.append(name)
        return value
    book_title = _text(field('title', work.get('title'), True)) or '[title unverified]'
    publisher = _text(field('publisher', meta.get('publisher'), True)) or '[publisher unverified]'
    year = _text(field('year', meta.get('publication_year') or meta.get('year'), True), 40) or '[year unverified]'
    editors = field('editors', _name_candidates(work, 'editor')) or []
    translators = field('translators', _name_candidates(work, 'translator')) or []
    book_authors = field('authors', _name_candidates(work, 'author')) or []
    citation_type = sb.get('type') or 'book'
    authors = book_authors; contribution_title = None
    if citation_type != 'book':
        authors = sb.get('authors') or []
        contribution_title = _text(sb.get('title')) or '[contribution title unverified]'
        for name in ('authors', 'title', 'type'):
            provenance['section.' + name] = _provenance(section_event, name)
            if (sb.get(name) is None if name == 'authors' else not sb.get(name)):
                missing.append('section.' + name)
            elif not _verified(section_event, name):
                review.append('section.' + name)
        if sb.get('short_title') and not _verified(section_event, 'short_title'):
            review.append('section.short_title')
        author_source = section_event.get('field_events', {}).get('authors', section_event)
        if author_source.get('origin') == 'source_byline' and any(person.get('literal') for person in authors):
            review.append('section.name_order')
            warnings.append('The closing byline and contributor list verify this author. Confirm the structured name or intended bibliography name order before academic submission; no surname order was guessed.')
        if sb.get('translators') is not None:
            translators = sb['translators']
            provenance['section.translators'] = _provenance(section_event, 'translators')
            if translators and not _verified(section_event, 'translators'):
                review.append('section.translators')
        if not editors and not book_authors:
            warnings.append('The contribution’s container has no verified author/editor credit.')
    elif section.get('attribution') != work.get('author') and (editors or 'unverified' in section.get('attribution', '').lower() or edits.get((section['id'], 'attribution'))):
        warnings.append('This draft cites the volume as a whole. Add structured section bibliography metadata to cite its chapter, poem, or entry under the actual contributor.')
        review.append('section.authorship')
    if not (authors or (citation_type == 'book' and (editors or translators))):
        # A confirmed explicit empty author list permits a genuinely anonymous work.
        target_event = section_event if citation_type != 'book' else work_event
        target_bib = sb if citation_type != 'book' else wb
        if target_bib.get('authors') != [] or not _verified(target_event, 'authors'):
            missing.append('authors')
    for label, people in [('authors', authors), ('editors', editors), ('translators', translators)]:
        if people and label not in wb and not (label in sb and citation_type != 'book'):
            warnings.append('Catalog ' + label + ' retain their supplied name order. Verify structured names for bibliography inversion and shortened notes.')
    chosen_locator = locator if locator is not None else sb.get('locator')
    resolved_locator = _locator(lib, row, block_rows[:2000], section, chosen_locator, warnings)
    if len(block_rows) > 2000:
        warnings.append('The passage spans more than 2,000 source blocks; locator coverage is incomplete. Supply a verified pinpoint locator.')
        review.append('locator.coverage')
    if not resolved_locator['value']:
        missing.append('locator')
    elif not resolved_locator.get('verified'):
        review.append('locator')
    edition = _text(field('edition', meta.get('edition')))
    volume = _text(field('volume', meta.get('volume')))
    volume_title = _text(field('volume_title', meta.get('volume_title')))
    short_title = _text(field('short_title')) or book_title
    canonical_url = _url(field('url'))
    doi = field('doi')
    if doi:
        canonical_url = doi if doi.startswith('https://doi.org/') else 'https://doi.org/' + doi
    file_ids = json.loads(row['data'])['file_ids']
    files = [cat['files'][fid] for fid in file_ids]
    formats = list(dict.fromkeys(Path(f['path']).suffix.lower().lstrip('.') for f in files))
    format_name = _text(field('format')) or ('EPUB' if formats == ['epub'] else ('Bookshare Word edition' if meta.get('bookshare_id') else 'Microsoft Word document') if formats == ['docx'] else 'Electronic edition')
    if 'url' in wb and canonical_url and not _verified(work_event, 'url'):
        review.append('url')
    if doi and not _verified(work_event, 'doi'):
        review.append('doi')
    data = {'type': citation_type, 'title': book_title, 'short_title': short_title,
            'contribution_title': contribution_title, 'contribution_short_title': _text(sb.get('short_title')) or contribution_title,
            'authors': authors, 'editors': editors, 'translators': translators, 'publisher': publisher,
            'year': year, 'edition': edition, 'volume': volume, 'volume_title': volume_title,
            'access': canonical_url or format_name, 'locator': resolved_locator}
    # Publication metadata from another edition cannot quietly be presented as checked.
    for key in ('edition_note', 'catalog_discrepancy', 'source_quality_note'):
        if meta.get(key):
            warnings.append(_text(meta[key], 1500))
            if not (_verified(work_event, 'year') and 'edition' in wb and _verified(work_event, 'edition')):
                review.append('edition_context')
    if review:
        warnings.append('Verify the listed candidate fields against this copy’s title/copyright pages and the cited passage. A copyright date alone may not identify the consulted edition.')
    if not work_event:
        warnings.append('No structured bibliography correction is recorded for this work; catalog details are citation candidates, not certified bibliographic data.')
    warnings.append('Plain text omits italics; use the HTML or Markdown variants to retain title formatting. Course-specific instructions can override Chicago 18.')
    versions = [{'file_id': f['id'], 'sha256': f.get('sha256'), 'path': f['path']} for f in files[:20]]
    identity_input = {'work_id': work['id'], 'edition_id': work.get('edition_id'), 'section_id': section['id'], 'passage_id': passage_id, 'source_hashes': [f.get('sha256') for f in files], 'locator': resolved_locator, 'style': STYLE}
    citation_id = 'citation_' + hashlib.sha256(json.dumps(identity_input, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:24]
    missing = list(dict.fromkeys(missing)); review = list(dict.fromkeys(review))
    return {'citation_id': citation_id, 'style': STYLE, 'style_name': STYLE_NAME, **_render(data),
            'html': _render(data, 'html'), 'markdown': _render(data, 'markdown'),
            'ready': not missing and not review, 'needs_review': bool(missing or review),
            'metadata_scope': 'passage' if contribution_target_id==passage_id else 'section',
            'contribution_target_id': contribution_target_id,
            'missing_fields': missing, 'review_fields': review, 'warnings': list(dict.fromkeys(warnings))[:30],
            'locator': resolved_locator, 'metadata': data, 'attribution': _text(section.get('attribution'), 2000),
            'provenance': provenance, 'source_identity': {**identity_input, 'files': versions, 'generation': lib._active().get('generation')},
            'links': {'local_passage': local_base_url(lib) + '/read/' + passage_id,
                      'local_citation': local_base_url(lib) + '/cite/' + passage_id,
                      'source_files': [f['path'] for f in files[:20]], 'canonical': canonical_url,
                      'acquisition': _url(meta.get('source_url')), 'style_guidance': RULE_URLS},
            'schema': SCHEMA}
