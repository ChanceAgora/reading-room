"""One local address for the listener and generated reading-room links."""
from __future__ import annotations

from urllib.parse import urlsplit

from .storage import read_json

DEFAULT_PORT = 18765
DEFAULT_BASE_URL = f'http://127.0.0.1:{DEFAULT_PORT}'
LOCAL_HOSTS = {'127.0.0.1', 'localhost', '::1'}


def _base_url(value):
    if not isinstance(value, str) or any(char.isspace() for char in value):
        raise ValueError('local_base_url must be an HTTP loopback address without whitespace.')
    try:
        parsed = urlsplit(value)
        port = parsed.port if parsed.port is not None else 80
        if (parsed.scheme != 'http' or parsed.hostname not in LOCAL_HOSTS or
                parsed.username is not None or parsed.password is not None or
                parsed.path not in ('', '/') or parsed.query or parsed.fragment or
                not 1 <= port <= 65535):
            raise ValueError
    except ValueError:
        raise ValueError('local_base_url must be an HTTP loopback address with a valid port and no path, query, or credentials.') from None
    host = f'[{parsed.hostname}]' if parsed.hostname == '::1' else parsed.hostname
    return f'http://{host}:{port}'


def local_base_url(lib):
    override = getattr(lib, '_local_base_url', None)
    if override is not None:
        return _base_url(override)
    configured = read_json(lib.state / 'config.json', {}).get('local_base_url', DEFAULT_BASE_URL)
    return _base_url(configured)


def server_address(lib, port=None):
    """Resolve a saved address, or an explicit port for this server instance."""
    base = local_base_url(lib)
    parsed = urlsplit(base)
    if port is not None:
        if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
            raise ValueError('Server port must be an integer from 1 to 65535.')
        host = f'[{parsed.hostname}]' if parsed.hostname == '::1' else parsed.hostname
        base = f'http://{host}:{port}'
    return parsed.hostname, port if port is not None else parsed.port, base
