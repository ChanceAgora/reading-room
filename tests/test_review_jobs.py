"""Paid review attempts must have durable, once-only request identity."""
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from book_library import review_jobs
from book_library.storage import atomic_json, read_json


@pytest.fixture
def library(tmp_path):
    return SimpleNamespace(state=tmp_path / '.library',
                           review_context=lambda _: {'revision': 'revision1', 'source_current': True})


def test_same_request_replays_across_instances_and_completion(library):
    first = review_jobs.begin_generation(library, 'work1', 'revision1', 'request1')
    assert not first['replay']
    reopened = SimpleNamespace(**vars(library))
    assert review_jobs.begin_generation(reopened, 'work1', 'revision1', 'request1')['replay']
    review_jobs.finish_generation(library, 'work1', 'request1')
    result = review_jobs.begin_generation(reopened, 'work1', 'revision1', 'request1')
    assert result['replay'] and result['status'] == 'complete'
    assert not review_jobs.generation_status(library, 'work1')['running']


def test_concurrent_requests_claim_only_once(library):
    def claim(number):
        try:
            return review_jobs.begin_generation(library, 'work1', 'revision1', f'request{number}')
        except ValueError:
            return None
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(claim, range(4)))
    assert sum(result is not None for result in results) == 1


def test_interruption_requires_new_explicit_request(library):
    review_jobs.begin_generation(library, 'work1', 'revision1', 'request1')
    path = library.state / 'review-jobs' / 'work1.json'
    journal = read_json(path)
    journal['requests']['request1']['expires_at'] = 0
    atomic_json(path, journal)
    before = path.read_bytes()
    assert review_jobs.generation_status(library, 'work1')['status'] == 'interrupted'
    assert path.read_bytes() == before  # Opening status neither retries nor writes.
    replay = review_jobs.begin_generation(library, 'work1', 'revision1', 'request1')
    assert replay['replay'] and replay['status'] == 'interrupted'
    assert not review_jobs.begin_generation(library, 'work1', 'revision1', 'request2')['replay']


def test_stale_or_missing_source_never_claims_request(library):
    with pytest.raises(ValueError, match='information changed'):
        review_jobs.begin_generation(library, 'work1', 'old', 'request1')
    library.review_context = lambda _: {'revision': 'revision1', 'source_current': False}
    with pytest.raises(ValueError, match='source changed'):
        review_jobs.begin_generation(library, 'work1', 'revision1', 'request1')
    assert not (library.state / 'review-jobs' / 'work1.json').exists()


def test_new_request_cannot_start_while_live_and_finished_requests_do_not_reopen(library):
    review_jobs.begin_generation(library, 'work1', 'revision1', 'request1')
    with pytest.raises(ValueError, match='already running'):
        review_jobs.begin_generation(library, 'work1', 'revision1', 'request2')
    review_jobs.finish_generation(library, 'work1', 'request1', status='failed')
    review_jobs.finish_generation(library, 'work1', 'request1', status='complete')
    assert review_jobs.generation_status(library, 'work1')['status'] == 'failed'
    assert not review_jobs.begin_generation(library, 'work1', 'revision1', 'request2')['replay']
