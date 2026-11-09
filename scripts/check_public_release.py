"""Check the exact Git/public package boundary; never inspect a user's books."""
from __future__ import annotations
import argparse
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / '.release-files.json').read_text())
PRIVATE = re.compile(rb'/Users/' + rb'sethwilson(?:/|\b)|(?:sk-proj-|sk-)[A-Za-z0-9_-]{28,}|gh[pousr]_[A-Za-z0-9]{30,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')


def allowed(name):
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts:
        return False
    if (path.name == '.env' or path.name.startswith('.env.')) and name != '.env.example':
        return False
    if any(p in MANIFEST['exclude_parts'] for p in path.parts) or path.suffix.lower() in MANIFEST['exclude_suffixes']:
        return False
    return name in MANIFEST['files'] or any(name.startswith(tree + '/') for tree in MANIFEST['trees'])


def candidates():
    result = set()
    for name in MANIFEST['files']:
        if (ROOT / name).is_file(): result.add(name)
    for tree in MANIFEST['trees']:
        for path in (ROOT / tree).rglob('*'):
            name = path.relative_to(ROOT).as_posix()
            if path.is_file() and allowed(name): result.add(name)
    return sorted(result)


def check(names, read):
    errors = []
    for name in names:
        if not allowed(name): errors.append(f'Outside public allowlist: {name}'); continue
        data = read(name)
        if PRIVATE.search(data): errors.append(f'Private path or credential-shaped content: {name}')
    return errors


def check_index():
    """Audit the blobs and modes Git will commit, independent of working files."""
    entries = subprocess.check_output(['git', 'ls-files', '--stage', '-z'], cwd=ROOT)
    blobs = {}
    errors = []
    for entry in entries.split(b'\0'):
        if not entry:
            continue
        metadata, raw_name = entry.split(b'\t', 1)
        mode, oid, stage = metadata.decode('ascii').split()
        name = raw_name.decode('utf-8', errors='surrogateescape')
        if stage != '0':
            errors.append(f'Unresolved Git index entry: {name}')
        elif mode not in {'100644', '100755'}:
            errors.append(f'Non-regular Git index entry: {name}')
        else:
            blobs[name] = oid
    if not entries:
        errors.append('No public files selected')
    errors += check(blobs, lambda name: subprocess.check_output(
        ['git', 'cat-file', 'blob', blobs[name]], cwd=ROOT,
    ))
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidates', action='store_true', help='Check selected working-tree files before initial staging')
    parser.add_argument('--list', action='store_true', help='Emit approved candidate paths, NUL-separated, for git add')
    parser.add_argument('--archive', type=Path, help='Inspect a built source archive or wheel')
    args = parser.parse_args()
    if args.archive:
        errors = []
        if args.archive.suffix == '.whl':
            with zipfile.ZipFile(args.archive) as archive:
                if 'book_library/frontend_dist/index.html' not in archive.namelist(): errors.append('Wheel lacks the built Reading Room UI')
                for name in archive.namelist():
                    if name.endswith('/'): continue
                    path = PurePosixPath(name)
                    permitted = name.startswith('book_library/') or (path.parts and path.parts[0].endswith('.dist-info'))
                    if not permitted or any(p in {'__pycache__', '.library', '.catalog', 'reports', '_work'} for p in path.parts): errors.append(f'Unexpected wheel entry: {name}')
                    if PRIVATE.search(archive.read(name)): errors.append(f'Private content: {name}')
        else:
            with tarfile.open(args.archive) as archive:
                files = {}
                for member in archive.getmembers():
                    if member.isdir(): continue
                    if not member.isfile(): errors.append(f'Non-regular archive entry: {member.name}'); continue
                    name = '/'.join(PurePosixPath(member.name).parts[1:])
                    if name == 'PKG-INFO':
                        if PRIVATE.search(archive.extractfile(member).read()): errors.append('Private package metadata')
                        continue
                    files[name] = member
                errors += check(files, lambda n: archive.extractfile(files[n]).read())
    elif args.candidates or args.list:
        names = candidates()
        errors = check(names, lambda n: (ROOT / n).read_bytes())
        errors += [f'Symlink cannot be published: {n}' for n in names if (ROOT / n).is_symlink()]
        if not names: errors.append('No public files selected')
        if args.list and not errors:
            sys.stdout.buffer.write(('\0'.join(names) + '\0').encode()); return 0
    else:
        errors = check_index()
    if errors:
        print('\n'.join(errors), file=sys.stderr); return 1
    print('Public file boundary and credential-pattern checks passed.'); return 0

if __name__ == '__main__': raise SystemExit(main())
