"""Install or remove only Reading Room's managed sibling skill symlinks."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

NAMES = ('bookshare-find', 'bookshare-download', 'library-search')
CHECKOUT = Path(__file__).resolve().parents[1]


def inspect_bundle(checkout, destination, *, legacy_roots=()):
    records = []
    for name in NAMES:
        source = checkout / 'skills' / name
        target = destination / name
        if not (source / 'SKILL.md').is_file():
            raise ValueError(f'The source skill {name} is incomplete. Restore the checkout before installing.')
        if target.is_symlink() and target.resolve() == source.resolve():
            state = 'managed'
        elif target.exists() or target.is_symlink():
            state = 'conflict'
        else:
            state = 'absent'
        duplicates = [str(root / name) for root in legacy_roots
                      if root != destination and ((root / name).exists() or (root / name).is_symlink())
                      and (root / name).resolve() != source.resolve()]
        records.append({'name': name, 'source': str(source.resolve()), 'destination': str(target),
                        'state': state, 'other_installed_copies': duplicates})
    return records


def manage(action, *, checkout=CHECKOUT, destination=None, home=None, project=False):
    home = Path(home or Path.home())
    default = home / '.agents' / 'skills'
    checkout = Path(checkout).resolve()
    if project:
        if destination is not None:
            raise ValueError('Choose project discovery or an explicit destination, not both.')
        destination = checkout / '.agents' / 'skills'
        for folder in (destination.parent, destination):
            if folder.is_symlink() or (folder.exists() and not folder.is_dir()):
                raise ValueError('Project skill discovery needs ordinary .agents/skills directories inside the checkout. Existing paths were left untouched.')
    destination = Path(destination or default).expanduser().absolute()
    legacy = [Path(os.environ.get('CODEX_HOME', str(home / '.codex'))) / 'skills'] if destination == default else []
    records = inspect_bundle(checkout, destination, legacy_roots=legacy)
    if action == 'status':
        return {'destination': str(destination), 'skills': records}
    if action in {'check', 'install'}:
        if any(item['state'] == 'conflict' or item['other_installed_copies'] for item in records):
            conflicts = ', '.join(item['name'] for item in records if item['state'] == 'conflict' or item['other_installed_copies'])
            raise ValueError(f'Existing skill copies conflict: {conflicts}. Nothing was changed. Use status to inspect them; preserve customized skills and resolve duplicates explicitly.')
        if action == 'check':
            return {'ready': True, 'destination': str(destination)}
        destination.mkdir(parents=True, exist_ok=True)
        created = []
        try:
            for item in records:
                if item['state'] == 'absent':
                    target = Path(item['destination'])
                    source = os.path.relpath(item['source'], destination) if project else item['source']
                    target.symlink_to(source, target_is_directory=True)
                    created.append(target)
        except OSError:
            for target in created:
                # Roll back only links just created by this invocation.
                if target.is_symlink() and target.resolve() == (checkout / 'skills' / target.name).resolve():
                    target.unlink()
            raise
        return {'installed': True, 'created': len(created), 'destination': str(destination),
                'message': 'Skills follow this checkout. Restart Codex if discovery does not refresh. Updating this checkout updates the linked skills.'}
    if action == 'uninstall':
        removed = []
        for item in records:
            if item['state'] == 'managed':
                Path(item['destination']).unlink()
                removed.append(item['name'])
        return {'removed': removed, 'preserved': [item['name'] for item in records if item['state'] == 'conflict'],
                'message': 'Only matching managed symlinks were removed. Books, settings, source checkout, and unrelated skills were retained.'}
    raise ValueError('Choose check, install, status, or uninstall.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['check', 'install', 'status', 'uninstall'])
    location = parser.add_mutually_exclusive_group()
    location.add_argument('--destination', type=Path)
    location.add_argument('--project', action='store_true', help='Manage checkout-local Codex discovery links instead of user-wide links')
    args = parser.parse_args()
    try:
        print(json.dumps(manage(args.action, destination=args.destination, project=args.project), indent=2))
        return 0
    except (OSError, ValueError) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
