"""LLMTR must not spend an unenforceable dollar budget."""

from contextlib import nullcontext
from decimal import Decimal

import pytest
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models import Model
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RequestUsage

from app.agents.capabilities.budget import (
    BudgetGuard,
    BudgetScope,
    SpendLedger,
    SpendLimit,
    guarded_by,
)
from app.agents.llmtr import LlmtrModel
from app.core.exceptions import BadRequestError
from app.services.model_catalog import LISTINGS, _read_listing

pytestmark = pytest.mark.anyio


async def answer(model: Model, streaming: bool, guard: BudgetGuard | None = None) -> None:
    agent = Agent(model, capabilities=[] if guard is None else [guard])
    # AgentRunnerService binds the complete run before the SDK creates streaming tasks.
    with guarded_by(guard) if guard is not None else nullcontext():
        if streaming:
            async with agent.run_stream("Say ready") as result:
                await result.get_output()
        else:
            await agent.run("Say ready")


def limited(provider: str = "llmtr", ledger: SpendLedger | None = None) -> BudgetGuard:
    return BudgetGuard(
        provider=provider,
        ledger=ledger or SpendLedger(),
        limits=[SpendLimit(BudgetScope.RUN, Decimal("1"))],
    )


@pytest.mark.security
@pytest.mark.parametrize("streaming", [False, True])
async def test_unpriced_primary_is_refused_before_any_paid_request(streaming: bool) -> None:
    inner = TestModel(model_name="llmtr/unpriced-native")
    guard = limited()
    with pytest.raises(BadRequestError, match="active dollar budget"):
        await answer(LlmtrModel(inner), streaming, guard)
    assert inner.last_model_request_parameters is None
    assert guard.ledger.total_usd == 0


@pytest.mark.security
async def test_unpriced_fallback_is_refused_under_another_providers_budget() -> None:
    def unavailable(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        raise ModelHTTPError(status_code=503, model_name="gpt-4o")

    fallback = TestModel(model_name="llmtr/unpriced-fallback")
    model = FallbackModel(FunctionModel(unavailable), LlmtrModel(fallback))
    with pytest.raises(BadRequestError, match="active dollar budget"):
        await answer(model, False, limited("openai"))
    assert fallback.last_model_request_parameters is None


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("empty_guard", [False, True])
async def test_unpriced_models_can_run_without_a_dollar_ceiling(
    streaming: bool, empty_guard: bool
) -> None:
    inner = TestModel(model_name="llmtr/unpriced-native")
    await answer(LlmtrModel(inner), streaming, BudgetGuard() if empty_guard else None)
    assert inner.last_model_request_parameters is not None


@pytest.mark.parametrize("streaming", [False, True])
async def test_priced_routed_model_records_known_spend(streaming: bool) -> None:
    guard = limited()
    inner = TestModel(model_name="gpt-4o")
    await answer(LlmtrModel(inner), streaming, guard)
    assert inner.last_model_request_parameters is not None
    assert guard.ledger.total_usd > 0 and not guard.ledger.has_unpriced_models


@pytest.mark.security
@pytest.mark.parametrize("streaming", [False, True])
async def test_an_incomplete_prior_bill_cannot_resume_a_dollar_budget(streaming: bool) -> None:
    ledger = SpendLedger()
    ledger.record("llmtr/unpriced-native", RequestUsage(input_tokens=1, output_tokens=1), "llmtr")
    inner = TestModel(model_name="gpt-4o")
    with pytest.raises(BadRequestError, match="active dollar budget"):
        await answer(LlmtrModel(inner), streaming, limited(ledger=ledger))
    assert inner.last_model_request_parameters is None


@pytest.mark.security
@pytest.mark.parametrize("streaming", [False, True])
async def test_auxiliary_llmtr_calls_obey_the_ambient_budget(streaming: bool) -> None:
    inner = TestModel(model_name="llmtr/unpriced-auxiliary")
    with guarded_by(limited()), pytest.raises(BadRequestError, match="active dollar budget"):
        await answer(LlmtrModel(inner), streaming)
    assert inner.last_model_request_parameters is None


def test_catalog_only_offers_chat_completions_models() -> None:
    models = _read_listing(
        {
            "data": [
                {"id": "chat", "supported_operations": ["CHAT_COMPLETIONS"]},
                {"id": "both", "supported_operations": ["CHAT_COMPLETIONS", "RESPONSES"]},
                {"id": "responses", "supported_operations": ["RESPONSES"]},
                {"id": "audio", "supported_operations": ["AUDIO_TRANSCRIPTIONS"]},
                {"id": "embedding", "supported_operations": ["EMBEDDINGS"]},
                {"id": "unknown"},
            ]
        },
        LISTINGS["llmtr"],
    )
    assert {model.id for model in models} == {"chat", "both"}
