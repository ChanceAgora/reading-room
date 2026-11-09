"""Run the checkout CLI with its optional private library-location binding."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys


def environment(checkout: Path, arguments: list[str], source=None) -> dict[str, str]:
    env = dict(os.environ if source is None else source)
    explicit = any(arg == '--root' or arg.startswith('--root=') for arg in arguments)
    binding = checkout / '.reading-room' / 'local.json'
    if not explicit and not env.get('LIBRARY_ROOT') and binding.exists():
        try:
            root = json.loads(binding.read_text()).get('library_root')
        except (OSError, ValueError, AttributeError):
            raise ValueError('The checkout library binding is invalid. Run bin/setup --root PATH again.') from None
        if not isinstance(root, str) or not Path(root).is_absolute():
            raise ValueError('The checkout library binding needs an absolute library_root. Run bin/setup --root PATH again.')
        permits_missing = bool(arguments and arguments[0] in {'init', 'doctor', 'demo'}) or any(arg in {'--help', '-h'} for arg in arguments)
        if not Path(root).is_dir() and not permits_missing:
            raise ValueError('The configured library directory is missing. Restore it or use --root PATH; no other library was selected.')
        env['LIBRARY_ROOT'] = root
        env['READING_ROOM_ROOT_SOURCE'] = 'checkout binding'
    return env


def main():
    checkout = Path(__file__).resolve().parents[1]
    try:
        env = environment(checkout, sys.argv[1:])
    except ValueError as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1
    os.execve(sys.executable, [sys.executable, '-m', 'book_library.cli', *sys.argv[1:]], env)


if __name__ == '__main__':
    raise SystemExit(main())
