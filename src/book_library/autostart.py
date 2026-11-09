"""Explicit management of one user-local macOS service; never replaces other jobs."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import plistlib
import subprocess
import sys

from .local_server import server_address
from .storage import atomic_json, read_json

LABEL = 'org.reading-room.library'


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manage(lib, action, *, port=None, checkout=None, home=None, run=subprocess.run):
    if sys.platform != 'darwin':
        raise ValueError('Login startup is supported only on macOS.')
    from .onboarding import checkout_path, port_in_use
    checkout = checkout or checkout_path()
    if checkout is None:
        raise ValueError('Login startup requires a source checkout. Use library serve manually.')
    checkout = Path(checkout).resolve()
    home = Path(home or Path.home())
    target = home / 'Library' / 'LaunchAgents' / f'{LABEL}.plist'
    record_path = checkout / '.reading-room' / 'autostart.json'
    record = read_json(record_path, {})
    exists = target.exists() or target.is_symlink()
    owned = bool(exists and not target.is_symlink() and record.get('path') == str(target)
                 and record.get('sha256') == _digest(target))
    domain = f'gui/{os.getuid()}'
    loaded = run(['launchctl', 'print', f'{domain}/{LABEL}'], capture_output=True, check=False).returncode == 0
    if action == 'status':
        return {'label': LABEL, 'installed': exists, 'managed_by_checkout': owned, 'loaded': loaded,
                'plist': str(target), 'message': 'Other login services are not modified.'}
    if action == 'remove':
        if not exists:
            return {'removed': False, 'message': 'No Reading Room login service is installed.'}
        if not owned:
            raise ValueError('This service was not installed by this checkout or was edited. It was left untouched; inspect its plist before removing it manually.')
        if loaded:
            result = run(['launchctl', 'bootout', domain, str(target)], capture_output=True, check=False)
            if result.returncode:
                raise ValueError('macOS could not stop the service. The plist and ownership record were preserved.')
        target.unlink()
        record_path.unlink(missing_ok=True)
        return {'removed': True, 'message': 'Login startup removed. Books and private library state were retained.'}
    if action != 'install':
        raise ValueError('Choose install, status, or remove.')
    host, selected_port, address = server_address(lib, port)
    if exists:
        if not owned:
            raise ValueError('A Reading Room login service already exists and is not owned by this checkout. It was left untouched.')
        expected_root = record.get('root')
        if expected_root != str(lib.root) or record.get('address') != address:
            raise ValueError('This checkout already manages another root or address. Remove that service explicitly before installing a different one.')
        return {'installed': True, 'already_installed': True, 'loaded': loaded, 'url': address,
                'message': 'The existing service was preserved.'}
    if loaded:
        raise ValueError('A service with this label is already loaded. It was left untouched.')
    if port_in_use(host, selected_port):
        raise ValueError('The selected port is already in use. Reuse the existing server or choose --port; no existing service was stopped.')
    python = checkout / '.venv' / 'bin' / 'python'
    if not python.is_file() or not lib.root.is_dir():
        raise ValueError('Complete bin/setup and a manual server start before installing login startup.')
    if not (checkout / 'src' / 'book_library' / 'frontend_dist' / 'index.html').is_file():
        raise ValueError('Build the frontend before installing login startup.')
    logs = lib.state / 'logs'
    logs.mkdir(parents=True, exist_ok=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {'Label': LABEL,
               'ProgramArguments': [str(python), '-m', 'book_library.cli', '--root', str(lib.root), 'serve', '--port', str(selected_port)],
               'WorkingDirectory': str(checkout), 'RunAtLoad': True, 'KeepAlive': True,
               'StandardOutPath': str(logs / 'server.log'), 'StandardErrorPath': str(logs / 'server-error.log')}
    # The service reads the existing credential-file reference from library
    # config. It deliberately does not copy shell variables or key values.
    with target.open('xb') as stream:
        plistlib.dump(payload, stream, sort_keys=True)
    os.chmod(target, 0o600)
    atomic_json(record_path, {'schema_version': 1, 'path': str(target), 'sha256': _digest(target),
                             'root': str(lib.root), 'address': address})
    result = run(['launchctl', 'bootstrap', domain, str(target)], capture_output=True, check=False)
    if result.returncode:
        # Only our newly written files are removed; existing jobs were checked
        # before writing. No server or source library is changed on this failure.
        target.unlink()
        record_path.unlink(missing_ok=True)
        raise ValueError('macOS could not load the login service. The new plist was removed; use library serve and check launchctl permissions.')
    return {'installed': True, 'loaded': True, 'label': LABEL, 'plist': str(target), 'url': address,
            'message': 'Login startup installed. Credential-file references come from private library configuration; shell credentials are not inherited.',
            'credential_file_configured': bool(read_json(lib.state / 'config.json', {}).get('openai_env_file'))}
