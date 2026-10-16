"""Limit arithmetic for calls (#54). Pure, so every edge is a one-liner."""

from decimal import Decimal

import pytest

from app.services import realtime_models
from app.services.voice.limits import (
    budget_refuses,
    call_cap_seconds,
    minutes_left_seconds,
    worst_case_usd,
)


@pytest.mark.parametrize(
    ("org_max", "agent_max", "elapsed", "left", "expected"),
    [
        (600, None, 0, None, 600),
        (600, 300, 0, None, 300),
        (600, 900, 0, None, 600),  # the agent cannot exceed the organization
        (3000, None, 0, None, 3000),
        (600, None, 200, None, 400),  # a reconnect carries the chain's minutes
        (600, None, 0, 120, 120),  # the month's minutes bind first
        (600, None, 700, None, 0),
    ],
)
def test_the_cap_is_the_tightest_limit(org_max, agent_max, elapsed, left, expected):
    assert (
        call_cap_seconds(
            org_max=org_max, agent_max=agent_max, chain_elapsed=elapsed, minutes_left=left
        )
        == expected
    )


def test_minutes_left_is_none_when_only_budgets_bind():
    assert minutes_left_seconds(monthly_minutes=None, used_seconds=10_000) is None
    assert minutes_left_seconds(monthly_minutes=10, used_seconds=300) == 300
    assert minutes_left_seconds(monthly_minutes=10, used_seconds=900) == 0


def test_the_worst_case_is_the_cap_times_the_worst_minute():
    entry = realtime_models.offered("openai", "gpt-realtime")
    assert worst_case_usd(cap_seconds=600, entry=entry) == Decimal("3.00")


@pytest.mark.security
def test_a_budget_that_cannot_cover_the_worst_case_refuses():
    assert budget_refuses(headroom=Decimal("2.99"), worst=Decimal("3.00"))
    assert not budget_refuses(headroom=Decimal("3.00"), worst=Decimal("3.00"))
    assert not budget_refuses(headroom=None, worst=Decimal("3.00"))
