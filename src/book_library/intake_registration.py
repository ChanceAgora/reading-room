"""Source-neutral, byte-preserving acquisition registration.

Registration records what arrived. It neither verifies bibliography nor starts
indexing or paid review. Provider observations remain candidates.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import stat
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile

from .storage import atomic_json, digest, now, read_json, stable, writer

FORMATS = {'.epub', '.docx'}
METADATA = {'title', 'author', 'authors', 'editors', 'translators', 'publisher', 'publication_year',
            'edition', 'volume', 'volume_title', 'isbn', 'source_url', 'catalog_title', 'catalog_isbn',
            'catalog_discrepancy', 'format', 'edition_verification', 'coverage'}


def _inside(path, root):
    return path == root or root in path.parents


def _natural(path):
    return tuple((0, int(bit)) if bit.isdigit() else (1, bit.casefold()) for bit in re.split(r'(\d+)', str(path)))


def _context(value):
    raw = copy.deepcopy(value or {})
    if not isinstance(raw, dict) or len(json.dumps(raw, ensure_ascii=False)) > 1_000_000:
        raise ValueError('Intake context must be a JSON object of at most one million characters.')
    if 'books' in raw:
        books = list(raw['books'].values()) if isinstance(raw['books'], dict) else raw['books']
        if not isinstance(books, list) or len(books) != 1 or not isinstance(books[0], dict):
            raise ValueError('Provide context for one book per intake.')
        book = books[0]
        files = book.get('files')
        if files is None:
            identity = book.get('bookshare_id')
            files = [f for f in raw.get('files', []) if identity is not None and str(f.get('bookshare_id')) == str(identity)]
        raw = {**book, 'files': files or [], 'provenance': {**raw.get('provenance', {}), **book.get('provenance', {})}}
    provider = raw.get('provider') or ('bookshare' if raw.get('bookshare_id') else 'local')
    if not isinstance(provider, str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,79}', provider):
        raise ValueError('Use a short provider name such as local, bookshare, or publisher.')
    provider_id = raw.get('provider_id', raw.get('bookshare_id'))
    if provider_id is not None:
        provider_id = str(provider_id)
        if not provider_id or len(provider_id) > 256 or any(ord(c) < 32 for c in provider_id):
            raise ValueError('The provider record identifier is not valid.')
    supplied = raw.get('metadata', raw)
    if not isinstance(supplied, dict):
        raise ValueError('Supplied metadata must be an object.')
    metadata = {key: copy.deepcopy(value) for key, value in supplied.items() if key in METADATA}
    from .citations import validate_bibliography
    for key, value in metadata.items():
        if value is None:
            continue
        if key in ('authors', 'editors', 'translators'):
            if not isinstance(value, list):
                raise ValueError('Contributor roles must contain lists of names.')
            validate_bibliography({key: [{'literal': person} if isinstance(person, str) else person for person in value]})
        elif key == 'publication_year':
            validate_bibliography({'year': value})
        elif not isinstance(value, str) or len(value) > 4000:
            raise ValueError('Supplied metadata values must be bounded text, except structured contributor lists and publication year.')
        if key == 'source_url' and value:
            validate_bibliography({'url': value})
    if any(len(json.dumps(value)) > 20_000 for value in metadata.values()):
        raise ValueError('Keep supplied metadata concise; book text belongs in the source file.')
    provenance = copy.deepcopy(raw.get('provenance', {}))
    if not isinstance(provenance, dict):
        raise ValueError('Acquisition provenance must be an object.')
    for key in ('source_file', 'source_sha256', 'source_bytes', 'archive_path', 'archive_sha256', 'archive_bytes', 'downloaded_at', 'format_reason'):
        if key in raw:
            provenance[key] = raw[key]
    evidence = raw.get('inspection_evidence', [])
    discrepancies = raw.get('discrepancies', [])
    if not isinstance(evidence, list) or len(evidence) > 100 or not isinstance(discrepancies, list) or len(discrepancies) > 100:
        raise ValueError('Use bounded lists of inspection evidence and discrepancies.')
    for item in evidence:
        if not isinstance(item, dict) or len(str(item.get('quote', ''))) > 2000:
            raise ValueError('Inspection evidence needs structured locations and short quotations.')
    label = raw.get('source_label') or ('Bookshare accessible export' if provider == 'bookshare' else 'Local copy' if provider == 'local' else provider)
    if not isinstance(label, str) or len(label) > 160:
        raise ValueError('Use a short source label.')
    return {**raw, 'provider': provider, 'provider_id': provider_id, 'metadata': metadata,
            'provenance': provenance, 'inspection_evidence': evidence, 'discrepancies': discrepancies, 'source_label': label}


def _regular(path):
    path = Path(path).expanduser()
    if path.is_symlink() or not path.is_file():
        raise ValueError('An acquisition source must be an existing regular file.')
    return path.resolve()


def _validate_provenance(provenance, files):
    """Validate retained packages when supplied, never require them for reindexing."""
    if provenance.get('archive_path') and provenance.get('source_file'):
        raise ValueError('Use either an archive source or a direct source for this acquisition.')
    verified = {'files_hashed': True, 'retained_source_checked': False}
    if provenance.get('archive_path'):
        archive = _regular(provenance['archive_path'])
        if provenance.get('archive_sha256') and digest(archive) != provenance['archive_sha256']:
            raise ValueError('The retained archive hash does not match its acquisition record.')
        try:
            with ZipFile(archive) as package:
                infos = package.infolist()
                names = [info.filename for info in infos]
                if len(names) != len(set(names)):
                    raise ValueError('The archive contains duplicate member names.')
                for info in infos:
                    name = PurePosixPath(info.filename)
                    if name.is_absolute() or '..' in name.parts or '\\' in info.filename or stat.S_ISLNK(info.external_attr >> 16):
                        raise ValueError('The archive contains an unsafe member path.')
                members = {i.filename for i in infos if not i.is_dir() and PurePosixPath(i.filename).suffix.lower() in FORMATS}
                mapped = [f.get('original_zip_member') for f in files]
                if len(mapped) != len(set(mapped)) or set(mapped) != members:
                    raise ValueError('The acquisition must map every book member exactly once in source order.')
                for file in files:
                    info = package.getinfo(file['original_zip_member'])
                    if info.file_size != file['bytes']:
                        raise ValueError('An archive member differs from the placed book file.')
                    sha = hashlib.sha256()
                    with package.open(info) as stream:
                        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                            sha.update(chunk)
                    if sha.hexdigest() != file['sha256']:
                        raise ValueError('An archive member differs from the placed book file.')
        except BadZipFile as exc:
            raise ValueError('The retained acquisition archive is not a valid ZIP.') from exc
        provenance.update(archive_path=str(archive), archive_sha256=digest(archive), archive_bytes=archive.stat().st_size)
        verified['retained_source_checked'] = True
    if provenance.get('source_file'):
        if len(files) != 1:
            raise ValueError('A direct source file describes exactly one placed book file.')
        source = _regular(provenance['source_file'])
        sha = digest(source)
        if sha != files[0]['sha256'] or provenance.get('source_sha256') not in (None, sha):
            raise ValueError('The placed file is not byte-identical to the retained source.')
        provenance.update(source_file=str(source), source_sha256=sha, source_bytes=source.stat().st_size)
        verified['retained_source_checked'] = True
    for file in files:
        if file.get('source_path'):
            source = _regular(file['source_path'])
            if digest(source) != file['sha256']:
                raise ValueError('A placed file differs from its source path.')
            file['source_path'] = str(source)
    return verified


def register_intake(lib, path, context=None):
    raw_path = Path(path).expanduser()
    path = raw_path.resolve()
    if raw_path.is_symlink() or not _inside(path, lib.root) or _inside(path, lib.state) or path == lib.root or not path.exists():
        raise ValueError('Choose one existing book file or folder inside the library, outside private state.')
    supplied = _context(context)
    provided = supplied.get('files')
    if provided is not None and not isinstance(provided, list):
        raise ValueError('Context files must be an ordered list.')
    if provided:
        selected = provided
    else:
        paths = [path] if path.is_file() else [p for p in path.rglob('*') if p.is_file() and not any(part.startswith('.') for part in p.relative_to(path).parts) and p.suffix.lower() in FORMATS]
        if len({p.parent for p in paths}) > 1:
            raise ValueError('Several source folders were found. Choose one book folder or supply its exact ordered parts.')
        if sum(p.suffix.lower() == '.epub' for p in paths) > 1 or len({p.suffix.lower() for p in paths}) > 1:
            raise ValueError('Several possible copies were found. Provide the exact ordered files for one book.')
        selected = [{'path': str(p)} for p in sorted(paths, key=_natural)]
    if not selected or len(selected) > 1000:
        raise ValueError('Choose between one and 1000 EPUB or Word parts for one book.')
    files = []
    for order, item in enumerate(selected):
        if not isinstance(item, dict) or not item.get('path'):
            raise ValueError('Every file entry needs a path.')
        original = Path(item['path']).expanduser()
        file_path = _regular(original)
        if file_path.suffix.lower() not in FORMATS or not _inside(file_path, path) or not _inside(file_path, lib.root) or any(p.startswith('.') for p in file_path.relative_to(lib.root).parts):
            raise ValueError('Every selected EPUB or Word file must be inside the requested book path.')
        file_stat = file_path.stat()
        sha = digest(file_path)
        if item.get('sha256') not in (None, sha) or item.get('bytes') not in (None, file_stat.st_size):
            raise ValueError('A supplied file fingerprint differs from the actual file.')
        sequence = item.get('sequence', order)
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0:
            raise ValueError('File sequence must be a nonnegative integer.')
        files.append({**{k: copy.deepcopy(item[k]) for k in ('scope', 'original_zip_member', 'source_path') if k in item},
                      'path': str(file_path), 'name': file_path.name, 'format': file_path.suffix[1:].lower(),
                      'sha256': sha, 'bytes': file_stat.st_size, 'mtime_ns': file_stat.st_mtime_ns, 'sequence': sequence})
    if len({f['path'] for f in files}) != len(files) or len({f['sequence'] for f in files}) != len(files):
        raise ValueError('File paths and reading-order positions must be unique.')
    files.sort(key=lambda f: f['sequence'])
    validation = _validate_provenance(supplied['provenance'], files)
    with writer(lib.state):
        catalog = lib._catalog()
        known = {f['path']: f for f in catalog['files'].values()}
        work_ids = {known[f['path']]['work_id'] for f in files if f['path'] in known}
        if len(work_ids) > 1:
            raise ValueError('These files already belong to different books. Intake each book separately.')
        source_folder = path.parent if path.is_file() else path
        selected_paths = {f['path'] for f in files}
        for neighbor in lib._inventory():
            shares_scope = Path(neighbor).parent == source_folder if path.is_file() else _inside(Path(neighbor), source_folder)
            if shares_scope and neighbor not in selected_paths:
                existing_neighbor = known.get(neighbor)
                if not existing_neighbor or existing_neighbor['work_id'] not in work_ids:
                    raise ValueError('Unselected book files share this folder. Keep distinct books in separate folders, or provide every ordered part of this one book; adjacent files cannot be silently merged.')
        if work_ids and not context:
            known_work = catalog['works'][next(iter(work_ids))]
            prior_sources = [a for a in catalog['acquisitions'].values() if a['work_id'] == known_work['id']]
            if prior_sources:
                prior_source = prior_sources[0]
                supplied['provider'] = prior_source.get('provider') or 'local'
                supplied['provider_id'] = prior_source.get('provider_id')
                supplied['source_label'] = known_work.get('metadata', {}).get('acquisition_source_label') or ('Bookshare accessible export' if supplied['provider'] == 'bookshare' else 'Local copy')
        requested_files = copy.deepcopy(files)
        hashes = [f['sha256'] for f in files]
        matches = []
        if not work_ids:
            for work_id in catalog['works']:
                existing = sorted([f for f in catalog['files'].values() if f['work_id'] == work_id and Path(f['path']).is_file()], key=lambda f: (f.get('sequence', 0), f['path']))
                if [f.get('sha256') for f in existing] == hashes and all(digest(f['path']) == f['sha256'] for f in existing):
                    matches.append(existing)
            if len(matches) > 1:
                raise ValueError('Identical copies belong to several existing records. Choose the intended existing book path.')
            if matches:
                old_files = matches[0]
                work_ids = {old_files[0]['work_id']}
                aliases = read_json(lib.state / 'source-aliases.json', {})
                for file, old in zip(files, old_files):
                    current = Path(old['path']).stat()
                    aliases[file['path']] = {'canonical_path': old['path'], 'sha256': file['sha256'],
                        'size': file['bytes'], 'mtime_ns': file['mtime_ns'], 'canonical_size': current.st_size, 'canonical_mtime_ns': current.st_mtime_ns,
                        'signature': [getattr(Path(file['path']).stat(), key) for key in ('st_dev', 'st_ino', 'st_ctime_ns')],
                        'canonical_signature': [getattr(current, key) for key in ('st_dev', 'st_ino', 'st_ctime_ns')]}
                    file.update(observed_path=file['path'], path=old['path'], name=Path(old['path']).name,
                                mtime_ns=current.st_mtime_ns, sequence=old.get('sequence', file['sequence']))
                atomic_json(lib.state / 'source-aliases.json', aliases)
        folder = catalog['works'][next(iter(work_ids))]['folder'] if work_ids else str(path.parent if path.is_file() else path)
        identity = stable('source', folder, *[f['sha256'] for f in files])
        if not context:
            for prior_path in sorted((lib.state / 'acquisitions').glob('*.json')):
                prior = read_json(prior_path, {})
                if prior.get('identity') == identity:
                    return prior
        record_id = stable('acquisition', identity, supplied['provider'], supplied.get('provider_id') or '')
        record_path = lib.state / 'acquisitions' / (record_id + '.json')
        existing = read_json(record_path)
        if existing:
            changed = any(existing.get('supplied_metadata', existing.get('metadata', {})).get(key) != value for key, value in supplied['metadata'].items())
            changed = changed or any(value and value != existing.get(key) for key, value in
                                    ((key, supplied[key]) for key in ('inspection_evidence', 'discrepancies')))
            changed = changed or any(existing.get('provenance', {}).get(key) != value for key, value in supplied['provenance'].items())
            if changed:
                raise ValueError('These files already have intake context with different information. The existing record is preserved; use its guided review to add or correct evidence instead of silently replacing the acquisition context.')
            return existing
        title = supplied['metadata'].get('title') or (catalog['works'][next(iter(work_ids))]['title'] if work_ids else path.stem if path.is_file() else path.name)
        candidates = [w['id'] for w in catalog['works'].values() if w['id'] not in work_ids and
                      (re.sub(r'\W', '', str(w.get('title', '')).casefold()) == re.sub(r'\W', '', str(title).casefold()) or
                       supplied['metadata'].get('isbn') and supplied['metadata']['isbn'] == w.get('metadata', {}).get('isbn'))]
        record = {'schema_version': 1, 'id': record_id, 'identity': identity, 'path': folder, 'folder': folder,
                  'provider': supplied['provider'], 'provider_id': supplied['provider_id'], 'source_label': supplied['source_label'],
                  'metadata': {**supplied['metadata'], 'title': title}, 'supplied_metadata': copy.deepcopy(supplied['metadata']),
                  'files': files, 'requested_files': requested_files,
                  'provenance': supplied['provenance'], 'inspection_evidence': supplied['inspection_evidence'],
                  'discrepancies': supplied['discrepancies'], 'validation': validation, 'existing_work_ids': sorted(work_ids),
                  'duplicate_candidates': candidates, 'created_at': now()}
        atomic_json(record_path, record)
        return record


def acquisition_books(lib):
    """Adapt canonical records to the existing identity/bootstrap pipeline."""
    result = []
    for path in sorted((lib.state / 'acquisitions').glob('*.json')):
        record = read_json(path, {})
        if record.get('schema_version') != 1 or not record.get('files'):
            continue
        metadata = copy.deepcopy(record['metadata'])
        metadata.update(folder=record['folder'], files=copy.deepcopy(record['files']),
                        acquisition_provider=record['provider'], acquisition_source_label=record['source_label'],
                        acquisition_context={'inspection_evidence': record.get('inspection_evidence', []),
                                             'discrepancies': record.get('discrepancies', [])},
                        _intake_acquisition_id=record['id'], _provider=record['provider'], _provider_id=record.get('provider_id'))
        if record['provider'] == 'bookshare' and record.get('provider_id'):
            metadata['bookshare_id'] = record['provider_id']
        result.append(metadata)
    return result


def grounded_inspection_leads(metadata, files, evidence):
    """Keep supplied inspection hints only when their file, location and quote agree.

    A matched hint is still a lead, never permission to apply the supplied value.
    Private paths stay out of the returned model-facing payload.
    """
    by_path = {file['path']: file for file in files}
    result = []
    for item in (metadata.get('acquisition_context') or {}).get('inspection_evidence', [])[:100]:
        if not isinstance(item, dict):
            continue
        file = by_path.get(item.get('path'))
        locator, quote = item.get('locator'), item.get('quote')
        if not file or item.get('sha256') != file.get('sha256') or not isinstance(locator, dict) or not locator or not isinstance(quote, str) or not quote:
            continue
        matches = [source for source in evidence if source.get('file_id') == file['id'] and quote in source['text']
                   and all(source.get('locator', {}).get(key) == value for key, value in locator.items())]
        if len(matches) == 1:
            result.append({'source_id': matches[0]['id'], 'quote': quote,
                           'field': str(item.get('field', ''))[:100], 'reported_value': item.get('value'),
                           'relationship': 'possible_lead'})
    return result[:20]
