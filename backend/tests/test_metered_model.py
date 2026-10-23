"""A capability's own model requests, streamed, stay inside the run's budget.

`MeteredModel` wraps a model a capability calls by itself - the browser's step,
a query expansion - so its requests are checked against the run's budget before
they are sent and booked to the run's ledger afterwards. The plain request path is
exercised through every capability that uses it; this is the streamed one.
"""

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from app.agents.capabilities._metered import MeteredModel
from app.agents.capabilities.budget import (
    BudgetExceeded,
    BudgetGuard,
    BudgetScope,
    SpendLedger,
    SpendLimit,
    guarded_by,
    metered_by,
)

pytestmark = pytest.mark.anyio


async def test_a_streamed_request_is_booked_once_it_has_been_read():
    ledger = SpendLedger()
    agent: Agent[None, str] = Agent(MeteredModel(TestModel(custom_output_text="streamed")))
    with metered_by(ledger):
        async with agent.run_stream("hello") as run:
            assert await run.get_output() == "streamed"
    assert ledger.input_tokens > 0


@pytest.mark.security
async def test_a_spent_budget_refuses_the_stream_before_it_opens():
    guard = BudgetGuard(
        ledger=SpendLedger(),
        limits=[
            SpendLimit(
                scope=BudgetScope.AGENT,
                limit_usd=Decimal("1.00"),
                period_spend=AsyncMock(return_value=Decimal("1.00")),
            )
        ],
    )
    agent: Agent[None, str] = Agent(MeteredModel(TestModel()))
    with guarded_by(guard), pytest.raises(BudgetExceeded):
        async with agent.run_stream("hello") as run:
            await run.get_output()
