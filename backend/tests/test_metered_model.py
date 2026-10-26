"""A capability's own model requests, streamed, stay inside the run's budget.

`MeteredModel` wraps a model a capability calls by itself - the browser's step,
a query expansion - so its requests are checked against the run's budget before
they are sent and booked to the run's ledger afterwards. The plain request path is
exercised through every capability that uses it; this is the streamed one.
"""

from collections.abc import AsyncIterator
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RequestUsage

from app.agents.capabilities._metered import MeteredModel
from app.agents.capabilities.budget import (
    BudgetExceeded,
    BudgetGuard,
    BudgetScope,
    SpendLedger,
    SpendLimit,
    guarded_by,
    metered_by,
    price_request,
)

pytestmark = pytest.mark.anyio


async def test_a_streamed_request_is_booked_once_it_has_been_read():
    ledger = SpendLedger()
    agent: Agent[None, str] = Agent(MeteredModel(TestModel(custom_output_text="streamed")))
    with metered_by(ledger):
        async with agent.run_stream("hello") as run:
            assert await run.get_output() == "streamed"
    assert ledger.input_tokens > 0


@pytest.mark.parametrize("streamed", [False, True])
@pytest.mark.parametrize("fail_primary", [False, True])
async def test_fallback_requests_book_the_answering_model_price(
    streamed: bool, fail_primary: bool
) -> None:
    def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(
            parts=[TextPart("answer")],
            model_name="gpt-4.1",
            usage=RequestUsage(input_tokens=100, output_tokens=100),
        )

    def primary(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if fail_primary:
            raise ModelHTTPError(status_code=503, model_name="primary", body="unavailable")
        return answer(messages, info)

    async def chunks(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        yield "answer"

    async def primary_chunks(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        if fail_primary:
            raise ModelHTTPError(status_code=503, model_name="primary", body="unavailable")
        yield "answer"

    model = FallbackModel(
        FunctionModel(primary, stream_function=primary_chunks, model_name="gpt-4.1"),
        FunctionModel(answer, stream_function=chunks, model_name="gpt-4.1"),
    )
    ledger = SpendLedger()
    agent: Agent[None, str] = Agent(MeteredModel(model))
    with metered_by(ledger):
        if streamed:
            async with agent.run_stream("hello") as run:
                assert await run.get_output() == "answer"
                usage = run.usage
        else:
            result = await agent.run("hello")
            usage = result.usage
    expected = price_request(usage, "gpt-4.1", None)
    assert expected is not None and expected > 0
    assert len(ledger.entries) == 1
    assert ledger.total_usd == expected
    assert not ledger.has_unpriced_models
    guard = BudgetGuard(
        ledger=ledger, limits=[SpendLimit(scope=BudgetScope.AGENT, limit_usd=expected)]
    )
    with guarded_by(guard), pytest.raises(BudgetExceeded):
        await agent.run("another paid request")
    assert len(ledger.entries) == 1


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
