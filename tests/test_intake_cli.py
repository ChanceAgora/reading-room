import json

import pytest

from book_library.cli import parser, run
from book_library.service import Library
from test_service import docx


def command(root, *args):
    return run(parser().parse_args(['--root', str(root), 'intake', *map(str, args), '--json']))


def test_cli_register_status_pause_resume_and_repeated_submission(tmp_path):
    source = docx(tmp_path / 'Book' / 'Book.docx', [('Heading1', 'Introduction'), 'An introductory explanation.'])
    context = tmp_path / 'context.json'
    context.write_text(json.dumps({'provider': 'publisher', 'metadata': {'title': 'New Book'}}))
    first = command(tmp_path, '--path', source, '--context', context)
    assert first['status'] == 'queued' and first['readiness']['text'] == 'pending'
    again = command(tmp_path, '--path', source)
    assert again['id'] == first['id'] and again['version'] == first['version']
    assert command(tmp_path, 'status')['intakes'][0]['id'] == first['id']
    paused = command(tmp_path, 'pause', first['id'], '--version', first['version'])
    assert paused['status'] == 'paused'
    with pytest.raises(ValueError, match='changed'):
        command(tmp_path, 'resume', first['id'], '--version', first['version'])
    resumed = command(tmp_path, 'resume', first['id'], '--version', paused['version'])
    assert resumed['status'] == 'queued'
    assert not (tmp_path / '.library' / 'costs.jsonl').exists()


def test_cli_intake_requires_an_explicit_path(tmp_path):
    with pytest.raises(ValueError, match='--path'):
        command(tmp_path)
    with pytest.raises(ValueError, match='identifier'):
        command(tmp_path, 'pause')


def test_ordinary_sync_does_not_authorize_intake(tmp_path):
    source = docx(tmp_path / 'Book' / 'Book.docx', ['Healthy source text.'])
    lib = Library(tmp_path)
    lib.sync(source, semantic=False)
    assert lib.intake_status() == {'intakes': []}
    assert not (lib.state / 'intakes').exists()
