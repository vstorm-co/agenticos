"""A row stamped by the database just past the window the API computed must not fail the stats.

The window comes from the API host's clock and `created_at` from the database's, so
a request made just after midnight UTC - or on a database ahead of the API host - can
fall on a day the window does not list.
"""

from datetime import date
from types import SimpleNamespace

from app.repositories.workflow_approval import OutcomeDay
from app.services.workflow_stats import _approval_days, _days

FIRST = date(2026, 10, 21)
AFTER = date(2026, 10, 28)


def test_an_approval_after_the_window_is_left_out_not_a_failure():
    days = _approval_days(
        FIRST,
        7,
        [OutcomeDay(AFTER, "approved", False, 1), OutcomeDay(FIRST, "rejected", False, 2)],
    )

    assert len(days) == 7
    assert days[0].rejected == 2
    assert sum(day.approved_unchanged for day in days) == 0


def test_a_run_after_the_window_is_left_out_not_a_failure():
    rows = [
        SimpleNamespace(day=AFTER, status="succeeded", runs=1, cost=0.5),
        SimpleNamespace(day=FIRST, status="failed", runs=3, cost=0.25),
    ]

    days = _days(FIRST, 7, rows)

    assert len(days) == 7
    assert (days[0].failed, days[0].cost_usd) == (3, 0.25)
    assert sum(day.succeeded for day in days) == 0
