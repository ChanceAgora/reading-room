"""Listener and generated links must agree without exposing a remote server."""
from __future__ import annotations

import pytest

from book_library import cli
from book_library.local_server import DEFAULT_BASE_URL, local_base_url, server_address
from book_library.storage import atomic_json, read_json
from test_citations import fixture


@pytest.mark.parametrize('saved,override,expected', [
    (None, None, 'http://127.0.0.1:18765'),
    ('http://127.0.0.1:19654', None, 'http://127.0.0.1:19654'),
    ('http://127.0.0.1:19654', 18766, 'http://127.0.0.1:18766'),
])
def test_cli_listener_and_citations_share_default_config_or_override(tmp_path, monkeypatch, saved, override, expected):
    import uvicorn
    lib, hit, _ = fixture(tmp_path)
    config = {'unrelated_setting': 'preserved'}
    if saved:
        config['local_base_url'] = saved
    atomic_json(lib.state / 'config.json', config)
    observed = []
    def run(app, **kwargs):
        citation = app.state.library.cite(hit['id'])
        observed.append((kwargs, citation['links']))
    monkeypatch.setattr(uvicorn, 'run', run)
    args = ['--root', str(lib.root), 'serve']
    if override is not None:
        args += ['--port', str(override)]
    cli.run(cli.parser().parse_args(args))
    options, links = observed[0]
    assert options == {'host': '127.0.0.1', 'port': int(expected.rsplit(':', 1)[1])}
    assert links['local_passage'] == expected + '/read/' + hit['id']
    assert links['local_citation'] == expected + '/cite/' + hit['id']
    assert read_json(lib.state / 'config.json') == config
    assert local_base_url(lib) == (saved or DEFAULT_BASE_URL)


def test_standalone_citations_follow_saved_address(tmp_path):
    lib, hit, _ = fixture(tmp_path)
    atomic_json(lib.state / 'config.json', {'local_base_url': 'http://localhost:19654/'})
    assert lib.cite(hit['id'])['links']['local_passage'] == 'http://localhost:19654/read/' + hit['id']


def test_ipv6_loopback_address_retains_brackets(tmp_path):
    lib, _, _ = fixture(tmp_path)
    atomic_json(lib.state / 'config.json', {'local_base_url': 'http://[::1]:18765'})
    assert server_address(lib, 18766) == ('::1', 18766, 'http://[::1]:18766')


@pytest.mark.parametrize('value', ['https://127.0.0.1:18765', 'http://example.com:18765',
    'http://0.0.0.0:18765', 'http://user:password@localhost:18765',
    'http://localhost:18765/path', 'http://localhost:18765?query=yes',
    'http://localhost:18765#fragment', 'http://localhost:0',
    'http://localhost:99999', 'http://localhost:18765\n', None])
def test_saved_address_rejects_remote_or_malformed_values(tmp_path, value):
    lib, _, _ = fixture(tmp_path)
    atomic_json(lib.state / 'config.json', {'local_base_url': value})
    with pytest.raises(ValueError, match='local_base_url'):
        server_address(lib)


@pytest.mark.parametrize('port', [0, -1, 65536, True])
def test_explicit_port_is_validated(tmp_path, port):
    lib, _, _ = fixture(tmp_path)
    with pytest.raises(ValueError, match='port'):
        server_address(lib, port)
