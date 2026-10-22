"""Limit arithmetic for calls (#54). Pure, so every edge is a one-liner."""

from decimal import Decimal

import pytest

from app.services import realtime_models
from app.services.voice.limits import budget_refuses, call_cap_seconds, worst_case_usd


@pytest.mark.parametrize(
    ("agent_max", "elapsed", "expected"),
    [
        (None, 0, 600),  # an agent that names none gets ten minutes
        (300, 0, 300),
        (3000, 0, 3000),
        (3600, 0, 3000),  # never past the ceiling below the provider's hour
        (None, 200, 400),  # a reconnect carries the chain's time
        (None, 700, 0),
    ],
)
def test_the_cap_is_the_agents_longest_call_less_the_chain(agent_max, elapsed, expected):
    assert call_cap_seconds(agent_max=agent_max, chain_elapsed=elapsed) == expected


def test_the_worst_case_is_the_cap_times_the_worst_minute():
    entry = realtime_models.offered("openai", "gpt-realtime")
    assert worst_case_usd(cap_seconds=600, entry=entry) == Decimal("3.00")


@pytest.mark.security
def test_a_budget_that_cannot_cover_the_worst_case_refuses():
    assert budget_refuses(headroom=Decimal("2.99"), worst=Decimal("3.00"))
    assert not budget_refuses(headroom=Decimal("3.00"), worst=Decimal("3.00"))
    assert not budget_refuses(headroom=None, worst=Decimal("3.00"))
