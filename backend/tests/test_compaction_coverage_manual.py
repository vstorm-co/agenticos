"""Forced summaries use the published strategy and account for their model cost."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.tools import RunContext
from pydantic_ai.usage import RequestUsage, RunUsage
from pydantic_ai_harness.compaction import SummarizingCompaction, TieredCompaction

from app.agents.capabilities.budget import (
    BudgetExceeded,
    BudgetGuard,
    BudgetScope,
    SpendLedger,
    SpendLimit,
    guarded_by,
    metered_by,
)
from app.agents.capabilities.compaction import (
    CompactionConfig,
    ContextGauge,
    MeteredCompaction,
    build_strategy,
)
from app.agents.capabilities.compaction._capability import NotifyingSummarizingCompaction

pytestmark = pytest.mark.anyio


def _history() -> list[ModelMessage]:
    return [
        ModelRequest(parts=[UserPromptPart(content="remember the agreed launch date")]),
        ModelResponse(parts=[TextPart(content="The launch is Friday")]),
        ModelRequest(parts=[UserPromptPart(content="keep that date")]),
    ]


@pytest.mark.parametrize("strategy", ["summarize", "tiered"])
async def test_forced_summary_runs_below_the_automatic_trigger_and_books_usage(
    strategy: str,
) -> None:
    sink = AsyncMock()
    gauge = ContextGauge()
    capability = MeteredCompaction(
        wrapped=build_strategy(
            CompactionConfig(strategy=strategy, context_window=100_000, keep_messages=1),
            gauge=gauge,
        )
    )
    ledger = SpendLedger()

    def summarize(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        assert "Friday" in str(messages)
        return ModelResponse(
            parts=[TextPart(content="The launch is Friday.")],
            usage=RequestUsage(
                input_tokens=43,
                output_tokens=7,
                cost=Decimal("0.25"),
                provider_reported_requests=1,
            ),
        )

    ctx = RunContext(
        deps=SimpleNamespace(on_compaction=sink), model=FunctionModel(summarize), usage=RunUsage()
    )
    history = _history()
    with metered_by(ledger):
        result = await capability.compact_now(history, ctx)
    assert result is not None and result != history
    assert "The launch is Friday." in str(result)
    assert result[-1] is history[-1]
    assert gauge.summarized is True
    assert ledger.total_usd == Decimal("0.25")
    assert (ledger.input_tokens, ledger.output_tokens) == (43, 7)
    assert [call.args[0].kind for call in sink.await_args_list] == [
        "compaction_started",
        "compaction_finished",
    ]


@pytest.mark.parametrize(
    "wrapped",
    [
        build_strategy(CompactionConfig(strategy="sliding_window")),
        SummarizingCompaction(max_messages=10),
        TieredCompaction(tiers=[SummarizingCompaction(max_messages=10)], target_tokens=100),
    ],
)
async def test_a_strategy_without_a_notifying_summary_leaves_manual_history_untouched(
    wrapped: object,
) -> None:
    ledger = SpendLedger()
    history = _history()
    capability = MeteredCompaction(wrapped=wrapped)
    with metered_by(ledger):
        assert (
            await capability.compact_now(
                history, RunContext(deps=None, model=TestModel(), usage=RunUsage())
            )
            is None
        )
    assert ledger.entries == []
    assert len(history) == 3


@pytest.mark.parametrize("fails", [False, True])
async def test_manual_summary_books_spend_before_raising_or_returning(
    monkeypatch: pytest.MonkeyPatch, fails: bool
) -> None:
    # The summary boundary can spend tokens and then fail after the provider answered.
    async def summary(
        self: object, messages: list[ModelMessage], ctx: RunContext[None]
    ) -> list[ModelMessage]:
        ctx.usage.incr(RequestUsage(input_tokens=12, output_tokens=3))
        if fails:
            raise RuntimeError("summary failed after spending")
        return messages[:1]

    monkeypatch.setattr(NotifyingSummarizingCompaction, "compact", summary)
    capability = MeteredCompaction(wrapped=build_strategy(CompactionConfig()))
    ledger = SpendLedger()
    ctx = RunContext(deps=None, model=TestModel(model_name=""), usage=RunUsage())
    history = _history()
    with metered_by(ledger):
        if fails:
            with pytest.raises(RuntimeError, match="after spending"):
                await capability.compact_now(_history(), ctx)
        else:
            assert await capability.compact_now(history, ctx) == history[:1]
    assert ledger.input_tokens == 12
    assert ledger.output_tokens == 3
    assert ledger.has_unpriced_models


@pytest.mark.security
async def test_a_forced_summary_rechecks_budget_after_booking_its_bill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def summary(
        self: object, messages: list[ModelMessage], ctx: RunContext[None]
    ) -> list[ModelMessage]:
        ctx.usage.incr(
            RequestUsage(input_tokens=12, cost=Decimal("0.5"), provider_reported_requests=1)
        )
        return messages[:1]

    monkeypatch.setattr(NotifyingSummarizingCompaction, "compact", summary)
    ledger = SpendLedger()
    guard = BudgetGuard(
        ledger=ledger, limits=[SpendLimit(scope=BudgetScope.RUN, limit_usd=Decimal("0.4"))]
    )
    capability = MeteredCompaction(wrapped=build_strategy(CompactionConfig()))
    with metered_by(ledger), guarded_by(guard), pytest.raises(BudgetExceeded):
        await capability.compact_now(
            _history(), RunContext(deps=None, model=TestModel(), usage=RunUsage())
        )
    assert ledger.total_usd == Decimal("0.5")


async def test_manual_summary_with_no_model_work_adds_no_ledger_entry() -> None:
    capability = MeteredCompaction(wrapped=build_strategy(CompactionConfig(keep_messages=20)))
    ledger = SpendLedger()
    history = _history()
    with metered_by(ledger):
        result = await capability.compact_now(
            history, RunContext(deps=None, model=TestModel(), usage=RunUsage())
        )
    assert result == history
    assert ledger.entries == []
