"""The command-line path preserves the same source and use scopes as the reader."""
import json

from book_library.cli import parser, run
from test_unit_reading import unit_book


def test_cli_selects_exact_source_and_records_resolved_selection_scope(tmp_path):
    lib, work_id, units = unit_book(tmp_path)
    def command(*args):
        return run(parser().parse_args(['--root', str(tmp_path / 'books'), *args]))
    outline = command('contents', work_id)
    assert outline['nodes']
    unit_id = next(unit['id'] for unit in units if unit['title'] == 'Chapter 1')
    reading = command('read-unit', unit_id)
    block = next(block for block in reading['blocks'] if 'naïve café' in block['text'])
    start = block['text'].index('naïve')
    selected = command('create-selection', unit_id, '--ranges', json.dumps([{'block_id': block['id'], 'start': start, 'end': start + 10}]))
    assert selected['quotation'] == 'naïve café'
    assert command('cite-selection', selected['id'])['target_scope'] == 'selection'
    assert command('cite-unit', unit_id)['target_scope'] == 'unit'
    assert lib.usage() == []
    command('usage', 'record', '--event', json.dumps({'target_scope': 'selection', 'target_id': selected['id'], 'work_id': 'forged', 'attribution': 'Forged Author', 'kind': 'used', 'purpose': 'research'}))
    saved = lib.usage()[0]
    assert saved['target_scope'] == 'selection'
    assert saved['selection_id'] == selected['id']
    assert saved['work_id'] == work_id
    assert saved.get('attribution') != 'Forged Author'
