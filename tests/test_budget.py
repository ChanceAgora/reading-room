"""Paid-request ceilings must survive retries, restarts, and interrupted logs."""
from decimal import Decimal

import pytest

from book_library.budget import Budget, BudgetExceeded


@pytest.fixture(autouse=True)
def accepted_test_budget(tmp_path):
    from book_library.storage import atomic_json
    atomic_json(tmp_path / 'config.json', {'settings_version': 1, 'budget': {
        'initial_usd': '50', 'monthly_usd': '25', 'timezone': 'America/Chicago',
        'accepted_at': 'fixture', 'approval_evidence': 'Explicit synthetic-test budget'}})


def test_timeout_reservations_survive_restart_and_retries_count(tmp_path):
    first = Budget(tmp_path)
    first.reserve(40_000_000, "pilot")  # $5.20; unknown request outcome
    restarted = Budget(tmp_path)
    assert restarted.report()["spent_or_reserved"]["pilot"] == pytest.approx(5.2)
    assert restarted.report()["uncertain_reservations"] == 1
    with pytest.raises(BudgetExceeded):
        restarted.reserve(40_000_000, "pilot")
    retry = restarted.reserve(30_000_000, "pilot")
    restarted.settle(retry, 30_000_000)
    report = Budget(tmp_path).report()
    assert report["spent_or_reserved"]["pilot"] == pytest.approx(9.1)
    assert report["requests"] == 2
    assert report["uncertain_reservations"] == 1
    assert report["actual_tokens"] == 30_000_000


def test_settlement_actual_usage_releases_only_known_excess(tmp_path):
    budget = Budget(tmp_path)
    request = budget.reserve(70_000_000)
    budget.settle(request, 60_000_000)
    assert Budget(tmp_path).report()["spent_or_reserved"]["pilot"] == pytest.approx(7.8)
    Budget(tmp_path).reserve(10_000_000)
    with pytest.raises(BudgetExceeded):
        Budget(tmp_path).reserve(10_000_000)


def test_full_build_needs_review_and_scopes_have_independent_caps(tmp_path):
    budget = Budget(tmp_path)
    with pytest.raises(BudgetExceeded):
        budget.reserve(1, scope="initial")
    budget.reserve(380_000_000, scope="initial", initial_approved=True)  # $49.40
    with pytest.raises(BudgetExceeded):
        budget.reserve(5_000_000, scope="initial", initial_approved=True)
    budget.reserve(70_000_000, scope="pilot")
    report = budget.report()
    assert report["ceilings"] == {"pilot": 10.0, "initial": 50.0, "monthly": 25.0}
    assert report["spent_or_reserved"]["initial"] == pytest.approx(49.4)
    assert report["spent_or_reserved"]["pilot"] == pytest.approx(9.1)


def test_monthly_cap_resets_at_calendar_boundary_without_erasing_history(tmp_path, monkeypatch):
    budget = Budget(tmp_path)
    monkeypatch.setattr(budget, "period", lambda scope: "2026-10" if scope == "monthly" else scope)
    october = budget.reserve(190_000_000, "monthly")
    with pytest.raises(BudgetExceeded):
        budget.reserve(3_000_000, "monthly")
    monkeypatch.setattr(budget, "period", lambda scope: "2026-11" if scope == "monthly" else scope)
    budget.reserve(10_000_000, "monthly")
    budget.settle(october, 190_000_000)  # delayed settlement still belongs to October
    assert budget.report()["spent_or_reserved"]["monthly"] == pytest.approx(1.3)
    assert budget._spent("monthly", "2026-10") == Decimal("24.7")
    assert budget.report()["requests"] == 2


def test_negative_usage_cannot_create_budget_credit(tmp_path):
    budget = Budget(tmp_path)
    with pytest.raises(ValueError):
        budget.reserve(-1000)
    request = budget.reserve(1000)
    with pytest.raises(ValueError):
        budget.settle(request, -1000)
    assert budget.report()["spent_or_reserved"]["pilot"] > 0


def test_settlement_is_idempotent_and_conflicting_retry_is_rejected(tmp_path):
    budget = Budget(tmp_path)
    request = budget.reserve(1000)
    budget.settle(request, 800)
    Budget(tmp_path).settle(request, 800)
    assert budget.report()["actual_tokens"] == 800
    with pytest.raises(ValueError):
        budget.settle(request, 0)
    assert budget.report()["spent_or_reserved"]["pilot"] == pytest.approx(800 * .13 / 1_000_000)


def test_settlement_must_correspond_to_real_reservation(tmp_path):
    with pytest.raises(ValueError):
        Budget(tmp_path).settle({"id": "unknown", "scope": "pilot", "period": "pilot"}, 1000)


def test_truncated_final_log_line_does_not_swallow_next_reservation(tmp_path):
    budget = Budget(tmp_path)
    budget.reserve(40_000_000)
    with budget.path.open("a") as f:
        f.write('{"kind":"reserve","request_id":"unfinished')
    Budget(tmp_path).reserve(30_000_000)
    assert Budget(tmp_path).report()["spent_or_reserved"]["pilot"] == pytest.approx(9.1)
    with pytest.raises(BudgetExceeded):
        Budget(tmp_path).reserve(10_000_000)
