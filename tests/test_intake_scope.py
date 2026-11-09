"""Queued scope checks are local and never authorize adjacent publications."""
import shutil

import pytest

from book_library import intake
from book_library.intake_registration import register_intake
from book_library.intake_scope import capture_scope, scope_current
from book_library.service import Library
from test_service import docx, seed


def job(lib, paths, requested_path=None):
    files = [{'path': str(path)} for path in paths]
    return {'files': files, 'source_scope': capture_scope(lib, files, requested_path=requested_path)}


def test_new_adjacent_file_is_not_added_to_a_queued_selection(tmp_path):
    selected = docx(tmp_path / 'Book' / 'Selected.docx', ['Selected publication.'])
    lib = Library(tmp_path)
    queued = job(lib, [selected], selected)
    assert scope_current(lib, queued)
    neighbor = docx(selected.parent / 'Unrequested.docx', ['Unrequested publication.'])
    assert not scope_current(lib, queued)
    assert not lib._active() and not lib.state.exists()
    neighbor.unlink()
    assert scope_current(lib, queued)


def test_capture_never_authorizes_a_neighbor_that_arrived_after_registration(tmp_path):
    selected = docx(tmp_path / 'Book' / 'Selected.docx', ['Selected publication.'])
    lib = Library(tmp_path)
    record = register_intake(lib, selected)
    docx(selected.parent / 'New arrival.docx', ['New unrelated publication.'])
    queued = {'files': record['files'], 'source_scope': capture_scope(lib, record['files'], requested_path=selected)}
    assert not scope_current(lib, queued)
    assert len(queued['source_scope']['allowed_paths']) == 1


def test_single_file_scope_does_not_include_books_in_child_folders(tmp_path):
    selected = docx(tmp_path / 'Standalone.docx', ['Selected publication.'])
    lib = Library(tmp_path)
    queued = job(lib, [selected], selected)
    docx(tmp_path / 'Another book' / 'Other.docx', ['A separate publication.'])
    assert scope_current(lib, queued)


def test_folder_scope_detects_new_nested_parts(tmp_path):
    selected = docx(tmp_path / 'Split' / 'First' / 'Part.docx', ['First selected part.'])
    lib = Library(tmp_path)
    queued = job(lib, [selected], selected.parent.parent)
    docx(selected.parent.parent / 'Second' / 'Part.docx', ['Unexpected second part.'])
    assert not scope_current(lib, queued)


def test_known_split_parts_are_allowed_and_missing_files_remain_source_check(tmp_path):
    first = docx(tmp_path / 'Split' / '01.docx', ['First selected part.'])
    second = docx(first.parent / '02.docx', ['Second selected part.'])
    lib = seed(tmp_path, [{'title': 'Split', 'paths': [first, second]}])
    queued = job(lib, [first, second], first)
    assert scope_current(lib, queued)
    second.unlink()
    assert scope_current(lib, queued)


def test_aliases_follow_indexing_visibility_and_old_records_remain_readable(tmp_path):
    original = docx(tmp_path / 'Original' / 'Book.docx', ['Original publication.'])
    lib = seed(tmp_path, [{'title': 'Original', 'paths': [original]}])
    duplicate = tmp_path / 'Download' / 'Book.docx'
    duplicate.parent.mkdir()
    shutil.copyfile(original, duplicate)
    record = register_intake(lib, duplicate)
    queued = {'files': record['files'], 'source_scope': capture_scope(lib, record['files'], requested_path=duplicate.parent)}
    assert scope_current(lib, queued)
    docx(duplicate, ['Different publication now.'])
    assert not scope_current(lib, queued)
    old = {'files': [{'path': str(original)}]}
    assert scope_current(lib, old)
    docx(original.parent / 'Neighbor.docx', ['New publication.'])
    assert not scope_current(lib, old)


def fake_review(monkeypatch):
    calls = []

    def suggest(library, context, **kwargs):
        calls.append(context['target']['id'])
        return {'status': 'complete', 'suggestions': [], 'unresolved': [],
                'assessments': [], 'warnings': [], 'model': 'fixture', 'cost': None}

    monkeypatch.setattr('book_library.review_ai.suggest', suggest)
    return calls


def drain(lib):
    for _ in range(30):
        if not intake.run_next(lib):
            return
    raise AssertionError('Fixture intake did not become idle.')


def test_queue_rejects_new_neighbor_before_index_and_requires_explicit_resume(tmp_path, monkeypatch):
    selected = docx(tmp_path / 'Book' / 'A.docx', [('Heading1', 'Selected heading'), 'Selected publication text.'])
    lib = Library(tmp_path)
    from book_library.public_config import accept_budget
    accept_budget(lib, approval_evidence='Synthetic fixture authorizes review.')
    queued = intake.enqueue_intake(lib, selected, review_metadata=True)
    neighbor = docx(selected.parent / 'B.docx', [('Heading1', 'Unrequested heading'), 'Unrequested publication text.'])
    calls = fake_review(monkeypatch)
    sync_calls = []
    original_sync = lib.sync

    def sync(*args, **kwargs):
        sync_calls.append((args, kwargs))
        return original_sync(*args, **kwargs)

    monkeypatch.setattr(lib, 'sync', sync)
    assert intake.run_next(lib)
    paused = intake.intake_status(lib, queued['id'])
    assert paused['status'] == 'paused' and paused['reason_code'] == 'scope_changed'
    assert paused['targets'] == []
    assert [file['path'] for file in paused['files']] == [str(selected)]
    assert not sync_calls and not calls and not lib._active()
    with pytest.raises(ValueError, match='[Uu]nselected'):
        intake.resume_intake(lib, queued['id'], expected_version=paused['version'])
    assert intake.intake_status(lib, queued['id'])['version'] == paused['version']
    neighbor.unlink()
    assert not intake.run_next(lib)  # Restoring scope is not itself authorization to resume.
    intake.resume_intake(lib, queued['id'], expected_version=paused['version'])
    drain(lib)
    done = intake.intake_status(lib, queued['id'])
    assert done['status'] == 'complete'
    assert [file['path'] for file in done['files']] == [str(selected)]
    assert all(target['title'] != 'Unrequested heading' for target in done['targets'])
    assert calls and set(calls).issubset({target['id'] for target in done['targets']})
    assert len(lib._catalog()['files']) == 1


def test_queue_new_neighbor_after_target_creation_does_not_expand_review(tmp_path, monkeypatch):
    selected = docx(tmp_path / 'Book' / 'A.docx', [('Heading1', 'Selected heading'), 'Selected publication text.'])
    lib = Library(tmp_path)
    queued = intake.enqueue_intake(lib, selected)
    calls = fake_review(monkeypatch)
    assert intake.run_next(lib)  # Publish exact text and establish the target list.
    indexed = intake.intake_status(lib, queued['id'])
    generation = lib._active()['generation']
    target_ids = [target['id'] for target in indexed['targets']]
    assert target_ids and not calls
    neighbor = docx(selected.parent / 'B.docx', [('Heading1', 'Unrequested heading'), 'Unrequested publication text.'])
    assert intake.run_next(lib)
    paused = intake.intake_status(lib, queued['id'])
    assert paused['status'] == 'paused' and paused['reason_code'] == 'scope_changed'
    assert [target['id'] for target in paused['targets']] == target_ids
    assert [file['path'] for file in paused['files']] == [str(selected)]
    assert lib._active()['generation'] == generation and len(lib._catalog()['files']) == 1
    assert not calls
    with pytest.raises(ValueError, match='[Uu]nselected'):
        intake.resume_intake(lib, queued['id'], expected_version=paused['version'])
    neighbor.unlink()
    intake.resume_intake(lib, queued['id'], expected_version=paused['version'])
    drain(lib)
    done = intake.intake_status(lib, queued['id'])
    assert done['status'] == 'complete'
    assert [target['id'] for target in done['targets']] == target_ids
    assert set(calls).issubset(set(target_ids))


def test_queue_selecting_one_known_part_captures_the_whole_existing_work(tmp_path, monkeypatch):
    first = docx(tmp_path / 'Split' / '01.docx', [('Heading1', 'First part'), 'First selected publication part.'])
    second = docx(first.parent / '02.docx', [('Heading1', 'Second part'), 'Second selected publication part.'])
    lib = seed(tmp_path, [{'title': 'Split', 'paths': [first, second]}])
    fake_review(monkeypatch)
    queued = intake.enqueue_intake(lib, first)
    assert {file['path'] for file in queued['files']} == {str(first), str(second)}
    assert set(queued['source_scope']['allowed_paths']) == {str(first), str(second)}
    drain(lib)
    done = intake.intake_status(lib, queued['id'])
    assert done['status'] == 'complete'
    assert {'First part', 'Second part'}.issubset({target['title'] for target in done['targets']})
