"""Generation and hosted search share the durable monthly library allowance."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest

from book_library.budget import Budget, BudgetExceeded, review_usage_cost


@pytest.fixture(autouse=True)
def accepted_test_budget(tmp_path):
    from book_library.storage import atomic_json
    atomic_json(tmp_path / 'config.json', {'settings_version': 1, 'budget': {
        'initial_usd': '50', 'monthly_usd': '25', 'timezone': 'America/Chicago',
        'accepted_at': 'fixture', 'approval_evidence': 'Explicit synthetic-test budget'}})


def usage(inputs=1000, outputs=100, cached=200, writes=300):
    return {'input_tokens': inputs, 'output_tokens': outputs,
            'input_tokens_details': {'cached_tokens': cached, 'cache_write_tokens': writes}}


def test_generation_prices_reads_writes_outputs_and_searches_separately():
    assert review_usage_cost(usage(), searches=2) == Decimal('0.0201395')
    assert review_usage_cost(usage(300_000, 100, 0, 0)) == Decimal('0.060075')
    with pytest.raises(ValueError):
        review_usage_cost({'input_tokens': 100, 'output_tokens': 20})
    with pytest.raises(ValueError):
        review_usage_cost(usage(100, 100, 200, 0))


def test_complete_review_releases_unused_stages_and_preserves_embedding_history(tmp_path):
    budget = Budget(tmp_path)
    embedding = budget.reserve(1_000_000, 'monthly')
    budget.settle(embedding, 1_000_000)
    reservation = budget.reserve_review()
    budget.begin_review_stage(reservation, 'local')
    budget.settle_review_stage(reservation, 'local', usage())
    receipt = budget.finish_review(reservation)
    assert receipt['dollars'] == '0.0001395'
    assert not receipt['uncertain']
    assert budget.finish_review(reservation) == receipt
    report = Budget(tmp_path).report()
    assert report['spent_or_reserved']['monthly'] == pytest.approx(.1301395)
    assert report['actual_tokens'] == 1_001_100
    assert report['requests'] == 2
    assert report['uncertain_reservations'] == 0


def test_timeout_retains_only_attempted_unknown_stage_and_survives_restart(tmp_path):
    budget = Budget(tmp_path)
    reservation = budget.reserve_review()
    budget.begin_review_stage(reservation, 'local')
    budget.settle_review_stage(reservation, 'local', usage())
    budget.begin_review_stage(reservation, 'web')
    receipt = Budget(tmp_path).finish_review(reservation)
    assert receipt['uncertain_stages'] == ['web']
    assert Decimal(receipt['dollars']) == Decimal('0.7431395')
    assert Budget(tmp_path).report()['uncertain_reservations'] == 1
    with pytest.raises(ValueError, match='already'):
        Budget(tmp_path).begin_review_stage(reservation, 'web')


def test_missing_usage_and_invalid_cache_lifetime_cannot_release_a_hold(tmp_path):
    budget = Budget(tmp_path)
    reservation = budget.reserve_review()
    budget.begin_review_stage(reservation, 'local')
    invalid = usage()
    del invalid['input_tokens_details']['cache_write_tokens']
    with pytest.raises(ValueError):
        budget.settle_review_stage(reservation, 'local', invalid)
    invalid = usage()
    invalid['input_tokens_details']['cache_write_tokens_details'] = {'ttl_30m_tokens': 0, 'ttl_12h_tokens': 300}
    with pytest.raises(ValueError):
        budget.settle_review_stage(reservation, 'local', invalid)
    assert budget.finish_review(reservation)['dollars'] == '0.004'


def test_stage_settlement_and_launch_are_idempotent_not_paid_retries(tmp_path):
    budget = Budget(tmp_path)
    reservation = budget.reserve_review()
    budget.begin_review_stage(reservation, 'local')
    with pytest.raises(ValueError):
        budget.begin_review_stage(reservation, 'local')
    budget.settle_review_stage(reservation, 'local', usage())
    budget.settle_review_stage(reservation, 'local', usage())
    with pytest.raises(ValueError):
        budget.settle_review_stage(reservation, 'local', usage(outputs=101))


def test_concurrent_reservations_and_embedding_share_monthly_ceiling(tmp_path):
    budget = Budget(tmp_path)
    embedding = budget.reserve(180_000_000, 'monthly')  # $23.40
    budget.settle(embedding, 180_000_000)
    def reserve(_):
        try:
            return Budget(tmp_path).reserve_review()
        except BudgetExceeded:
            return None
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(reserve, range(4)))
    assert sum(result is not None for result in results) == 2
    assert budget.report()['spent_or_reserved']['monthly'] == pytest.approx(24.9)


def test_review_settles_to_original_month_and_stops_after_overrun(tmp_path, monkeypatch):
    budget = Budget(tmp_path)
    monkeypatch.setattr(budget, 'period', lambda scope: '2026-10')
    reservation = budget.reserve_review()
    budget.begin_review_stage(reservation, 'local')
    budget.settle_review_stage(reservation, 'local', usage(100_000, 4000, 0, 0))
    with pytest.raises(BudgetExceeded):
        budget.begin_review_stage(reservation, 'web')
    monkeypatch.setattr(budget, 'period', lambda scope: '2026-11')
    receipt = budget.finish_review(reservation)
    assert receipt['period'] == '2026-10'
    assert budget.report()['spent_or_reserved']['monthly'] == 0
    assert budget._spent('monthly', '2026-10') == Decimal('0.012')
