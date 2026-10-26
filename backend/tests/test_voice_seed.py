"""What a reconnect hands the new session: text, never audio (#54, amendment 9)."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic_ai import Agent
from pydantic_ai.messages import ModelRequest, ModelResponse
from pydantic_ai.models.instrumented import InstrumentationSettings

from app.services.voice.seed import RECENT_TURNS_KEPT, seed_history

pytestmark = pytest.mark.anyio


def _rows(n: int, size: int = 20):
    return [
        SimpleNamespace(
            role="user" if i % 2 == 0 else "assistant",
            content=f"turn {i} " + "x" * size,
            context_used_tokens=None,
        )
        for i in range(n)
    ]


async def test_a_short_history_is_seeded_verbatim():
    summarise = AsyncMock()
    with patch(
        "app.services.voice.seed.conversation_repo.get_recent_messages",
        AsyncMock(return_value=_rows(4)),
    ):
        seeded = await seed_history(
            MagicMock(), conversation_id=uuid4(), context_window=32_000, summarise=summarise
        )
    assert [type(m) for m in seeded] == [ModelRequest, ModelResponse, ModelRequest, ModelResponse]
    summarise.assert_not_awaited()


async def test_the_summary_is_written_by_the_chat_model_and_booked_on_the_run():
    from pydantic_ai.models.test import TestModel

    from app.agents.capabilities.budget import BudgetGuard, SpendLedger
    from app.services.voice.seed import summariser

    ledger = SpendLedger()
    prepared = SimpleNamespace(
        built=SimpleNamespace(
            agent=Agent(TestModel(custom_output_text="A summary.")),
            budget=BudgetGuard(ledger=ledger, limits=[]),
            ledger=ledger,
        )
    )
    assert await summariser(prepared)("user: hello") == "A summary."
    assert len(ledger.entries) == 1


@pytest.mark.security
@pytest.mark.parametrize("include_content", [False, True])
async def test_voice_summary_inherits_content_policy_and_trace_destination(
    monkeypatch: pytest.MonkeyPatch, include_content: bool
) -> None:
    from pydantic_ai.models.test import TestModel

    from app.agents.capabilities.budget import BudgetGuard, SpendLedger
    from app.services.voice.seed import summariser

    exporters = [InMemorySpanExporter(), InMemorySpanExporter()]
    providers = [TracerProvider(), TracerProvider()]
    for provider, exporter in zip(providers, exporters, strict=True):
        provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(
        Agent,
        "_instrument_default",
        InstrumentationSettings(tracer_provider=providers[0], include_content=True),
    )
    host = Agent(TestModel(custom_output_text="A summary."))
    host.instrument = InstrumentationSettings(
        tracer_provider=providers[1], include_content=include_content
    )
    ledger = SpendLedger()
    prepared = SimpleNamespace(
        built=SimpleNamespace(agent=host, budget=BudgetGuard(ledger=ledger), ledger=ledger)
    )
    try:
        assert await summariser(prepared)("synthetic confidential voice transcript") == "A summary."
        assert exporters[0].get_finished_spans() == ()
        spans = exporters[1].get_finished_spans()
        assert spans
        recorded = json.dumps([dict(span.attributes or {}) for span in spans], default=str)
        assert ("synthetic confidential voice transcript" in recorded) is include_content
    finally:
        for provider in providers:
            provider.shutdown()


@pytest.mark.security
async def test_no_summary_is_made_when_the_budget_cannot_afford_one():
    from pydantic_ai.models.test import TestModel

    from app.agents.capabilities.budget import BudgetGuard, SpendLedger
    from app.services.voice.seed import summariser

    ledger = SpendLedger()
    guard = BudgetGuard(ledger=ledger, limits=[])
    guard.can_afford_next_request = AsyncMock(return_value=False)
    prepared = SimpleNamespace(
        built=SimpleNamespace(agent=SimpleNamespace(model=TestModel()), budget=guard, ledger=ledger)
    )
    assert await summariser(prepared)("user: hello") == ""
    assert ledger.entries == []


async def test_a_history_past_half_the_window_is_a_summary_plus_the_recent_turns():
    summarise = AsyncMock(return_value="They asked about invoices for Acme.")
    rows = _rows(60, size=2_000)  # ~120k chars against a 32k-token window
    with patch(
        "app.services.voice.seed.conversation_repo.get_recent_messages",
        AsyncMock(return_value=rows),
    ):
        seeded = await seed_history(
            MagicMock(), conversation_id=uuid4(), context_window=32_000, summarise=summarise
        )
    summarise.assert_awaited_once()
    assert "They asked about invoices for Acme." in seeded[0].parts[0].content
    assert len(seeded) <= RECENT_TURNS_KEPT + 1
    assert sum(len(str(p.content)) for m in seeded for p in m.parts) <= 32_000 * 0.5 * 4


async def test_recent_turns_too_long_to_keep_whole_are_dropped_oldest_first():
    """Twelve recent turns can themselves overflow a small window; the seed still fits."""
    summarise = AsyncMock(return_value="")
    rows = _rows(20, size=4_000)
    with patch(
        "app.services.voice.seed.conversation_repo.get_recent_messages",
        AsyncMock(return_value=rows),
    ):
        seeded = await seed_history(
            MagicMock(), conversation_id=uuid4(), context_window=8_000, summarise=summarise
        )
    assert sum(len(str(p.content)) for m in seeded for p in m.parts) <= 8_000 * 0.5 * 4 // 2
    assert len(seeded) < RECENT_TURNS_KEPT
