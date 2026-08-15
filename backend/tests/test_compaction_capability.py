"""Tests for the compaction capability.

What is guarded: the configuration reaches the strategy it names, a summary the
strategy pays for is booked against the run that paid for it, and compaction
never leaves a tool return without the call it answers - which is what a resumed
approval replays through.
"""

from dataclasses import dataclass
from typing import Any

import pytest
from pydantic import ValidationError
from pydantic_ai._run_context import RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import ModelRequestContext, ModelRequestParameters
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage
from pydantic_ai_harness.compaction import (
    ClearToolResults,
    SlidingWindowCompaction,
    SummarizingCompaction,
    TieredCompaction,
)

from app.agents.capabilities import CapabilityBinding, build, get
from app.agents.capabilities.budget import SpendLedger, metered_by
from app.agents.capabilities.compaction import (
    CompactionConfig,
    MeteredCompaction,
    build_strategy,
)

pytestmark = pytest.mark.anyio


def _request_context(messages: list[ModelMessage], *, model: Any = None) -> ModelRequestContext:
    return ModelRequestContext(
        model=model if model is not None else TestModel(),
        messages=messages,
        model_settings=None,
        model_request_parameters=ModelRequestParameters(),
    )


def _run_context(usage: RunUsage | None = None) -> RunContext[None]:
    return RunContext(deps=None, model=TestModel(), usage=usage or RunUsage())


@dataclass
class _Spender(AbstractCapability[Any]):
    """A stand-in strategy that spends what a summary call would spend.

    The real `SummarizingCompaction` reaches a provider, so the thing under test
    - that whatever lands in `ctx.usage` during the hook is booked - is asserted
    against a capability that adds to it directly.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    raises: bool = False

    async def before_model_request(
        self, ctx: RunContext[Any], request_context: ModelRequestContext
    ) -> ModelRequestContext:
        ctx.usage.input_tokens += self.input_tokens
        ctx.usage.output_tokens += self.output_tokens
        ctx.usage.cache_read_tokens += self.cache_read_tokens
        ctx.usage.cache_write_tokens += self.cache_write_tokens
        if self.raises:
            raise RuntimeError("the summary call failed after it was billed")
        return request_context


class TestConfiguration:
    def test_the_default_strategy_spends_the_cheap_passes_first(self):
        """Summarising is the expensive answer, so it must not be the first one."""
        assert isinstance(build_strategy(CompactionConfig()), TieredCompaction)

    @pytest.mark.parametrize(
        ("strategy", "expected"),
        [
            ("clear_tool_results", ClearToolResults),
            ("sliding_window", SlidingWindowCompaction),
            ("summarize", SummarizingCompaction),
            ("tiered", TieredCompaction),
        ],
    )
    def test_each_strategy_name_reaches_the_strategy_it_names(self, strategy, expected):
        built = build_strategy(CompactionConfig(strategy=strategy))
        assert isinstance(built, expected)

    def test_the_tiered_strategy_clears_before_it_summarizes(self):
        """Order is the whole point of tiering: the cheap tier has to run first."""
        tiered = build_strategy(CompactionConfig(strategy="tiered"))
        assert isinstance(tiered, TieredCompaction)
        assert [type(tier) for tier in tiered.tiers] == [ClearToolResults, SummarizingCompaction]

    def test_the_window_override_reaches_every_tier(self):
        """A tier left on the registry's number is a tier with a different trigger."""
        tiered = build_strategy(
            CompactionConfig(
                strategy="tiered", context_window=32_000, fallback_context_window=8_000
            )
        )
        assert isinstance(tiered, TieredCompaction)
        assert tiered.context_window == 32_000
        assert [tier.context_window for tier in tiered.tiers] == [32_000, 32_000]
        assert [tier.fallback_context_window for tier in tiered.tiers] == [8_000, 8_000]

    def test_the_knobs_reach_the_single_strategies(self):
        clearing = build_strategy(
            CompactionConfig(strategy="clear_tool_results", keep_tool_pairs=7, max_fraction=0.5)
        )
        assert isinstance(clearing, ClearToolResults)
        assert (clearing.keep_pairs, clearing.max_fraction) == (7, 0.5)

        window = build_strategy(CompactionConfig(strategy="sliding_window", keep_messages=9))
        assert isinstance(window, SlidingWindowCompaction)
        assert window.keep_messages == 9

        summary = build_strategy(
            CompactionConfig(strategy="summarize", keep_messages=4, fallback_context_window=64_000)
        )
        assert isinstance(summary, SummarizingCompaction)
        assert (summary.keep_messages, summary.fallback_context_window) == (4, 64_000)

    @pytest.mark.parametrize(
        "blob",
        [
            {"strategy": "compact_everything"},
            {"max_fraction": 1.5},
            {"max_fraction": 0.0},
            {"keep_messages": 0},
            {"keep_tool_pairs": -1},
            {"context_window": 10},
            {"fallback_context_window": 10},
        ],
    )
    def test_a_configuration_that_cannot_work_is_refused_at_publish(self, blob):
        """Every one of these produces a strategy that refuses itself at build time.

        Refused here rather than there: the schema is what the Builder renders a
        form from, so a bound that only exists inside the harness is a bound
        somebody meets mid-run instead of while looking at the field.
        """
        with pytest.raises(ValidationError):
            CompactionConfig.model_validate(blob)


class TestRegistration:
    def test_it_is_registered_without_tools(self):
        """Rewriting a history is not an action anybody approves, so it declares none."""
        definition = get("compaction")
        assert definition.tools == ()
        assert definition.side_effecting is False
        assert definition.config_schema is CompactionConfig

    def test_an_empty_config_blob_still_builds(self):
        """A capability that answers `None` drops out of the registry's drift check."""
        built = build([CapabilityBinding(capability_id="compaction")])
        assert isinstance(built[0], MeteredCompaction)
        assert built[0].id == "compaction"

    def test_an_agent_that_does_not_bind_it_gets_nothing(self):
        """Binding is the decision to compact; there is no other way to switch it on."""
        assert build([]) == []


class TestMetering:
    async def test_a_summary_is_booked_against_the_run_that_paid_for_it(self):
        """`SummarizingCompaction` runs its own agent, which no BudgetGuard wraps.

        Without this the tokens land in `ctx.usage` and nowhere else: the run
        under-reports its cost and no cap can stop a compaction loop.
        """
        ledger = SpendLedger()
        capability = MeteredCompaction(
            wrapped=_Spender(input_tokens=1_200, output_tokens=300, cache_read_tokens=200)
        )

        with metered_by(ledger):
            await capability.before_model_request(_run_context(), _request_context([]))

        assert len(ledger.entries) == 1
        assert (ledger.input_tokens, ledger.output_tokens) == (1_200, 300)

    async def test_a_strategy_that_calls_no_model_books_nothing(self):
        """The zero-LLM strategies are wrapped too, and must stay free."""
        ledger = SpendLedger()
        capability = MeteredCompaction(wrapped=_Spender())

        with metered_by(ledger):
            await capability.before_model_request(_run_context(), _request_context([]))

        assert ledger.entries == []

    async def test_tokens_spent_before_a_failure_are_still_booked(self):
        """A strategy that raised after its summary call still spent the tokens."""
        ledger = SpendLedger()
        capability = MeteredCompaction(wrapped=_Spender(input_tokens=500, raises=True))

        with metered_by(ledger), pytest.raises(RuntimeError):
            await capability.before_model_request(_run_context(), _request_context([]))

        assert ledger.input_tokens == 500

    async def test_a_model_the_registry_cannot_price_is_booked_as_partial(self):
        """Not dropped, and not attributed to a guess.

        A spec with fallbacks builds a `FallbackModel` whose composite id prices
        against nothing. The entry still exists, so the run reports its tokens and
        marks its cost partial rather than reporting a total that is quietly short.
        """
        ledger = SpendLedger()
        capability = MeteredCompaction(wrapped=_Spender(input_tokens=100, output_tokens=10))

        with metered_by(ledger):
            await capability.before_model_request(
                _run_context(), _request_context([], model=_UnpricedModel())
            )

        assert ledger.has_unpriced_models
        assert ledger.input_tokens == 100

    async def test_a_model_that_names_itself_with_nothing_is_booked_as_unknown(self):
        """A blank name prices against nothing and reads in a log as an absent field.

        `model_name` is abstract, so it is always there - but at least one core
        implementation answers `''` for a response that carried none.
        """
        ledger = SpendLedger()
        capability = MeteredCompaction(wrapped=_Spender(input_tokens=100))

        with metered_by(ledger):
            await capability.before_model_request(
                _run_context(), _request_context([], model=_NamelessModel())
            )

        assert [entry.model_name for entry in ledger.entries] == ["unknown"]

    async def test_the_wrapped_strategy_still_edits_the_request(self):
        """Metering is a wrapper, not a replacement - the compaction has to happen."""
        capability = MeteredCompaction(
            wrapped=build_strategy(_triggers_immediately("sliding_window"))
        )
        messages = [_user(f"turn {index}: " + "words " * 20) for index in range(20)]

        request_context = await capability.before_model_request(
            _run_context(), _request_context(list(messages))
        )

        assert len(request_context.messages) < len(messages)


class TestToolPairingSurvives:
    async def test_a_parked_tool_call_keeps_the_call_its_return_answers(self):
        """What a resumed approval replays through.

        A parked run dumps `all_messages()` into `paused_state`, and the resume
        hands it back as history with the approved call's result keyed on the
        tool-call id. Compaction that dropped the `ModelResponse` holding that
        `ToolCallPart` would leave an orphaned return, which every provider
        rejects - and it would do so on the one request a person has just
        approved.
        """
        history: list[ModelMessage] = []
        for index in range(30):
            history.append(_user(f"do thing {index}"))
            history.append(
                ModelResponse(
                    parts=[ToolCallPart(tool_name="ls", args={}, tool_call_id=f"c{index}")]
                )
            )
            history.append(
                ModelRequest(
                    parts=[ToolReturnPart(tool_name="ls", content="ok", tool_call_id=f"c{index}")]
                )
            )
        history.append(ModelResponse(parts=[TextPart(content="done")]))

        capability = MeteredCompaction(
            wrapped=build_strategy(_triggers_immediately("sliding_window", keep_messages=3))
        )
        request_context = await capability.before_model_request(
            _run_context(), _request_context(list(history))
        )

        assert len(request_context.messages) < len(history)
        assert _orphaned_returns(request_context.messages) == set()


def _triggers_immediately(strategy: str, *, keep_messages: int = 1) -> CompactionConfig:
    """A configuration whose trigger a handful of short messages can reach.

    `TestModel` is not in the pricing registry, so a fraction is taken of
    `fallback_context_window`, and the default 200K puts the trigger far beyond
    anything a test would build. Pinning the window is what the harness
    documents for exactly this - the alternative is a test that passes because
    compaction never ran.
    """
    return CompactionConfig(
        strategy=strategy,
        keep_messages=keep_messages,
        max_fraction=0.05,
        context_window=1_000,
    )


def _user(text: str) -> ModelRequest:
    return ModelRequest(parts=[UserPromptPart(content=text)])


def _orphaned_returns(messages: list[ModelMessage]) -> set[str]:
    """Tool-call ids answered by a return whose call is no longer in the history."""
    called = {
        part.tool_call_id
        for message in messages
        if isinstance(message, ModelResponse)
        for part in message.parts
        if isinstance(part, ToolCallPart)
    }
    returned = {
        part.tool_call_id
        for message in messages
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    }
    return returned - called


class _UnpricedModel(TestModel):
    """A model whose name resolves against no price, as a `FallbackModel`'s does."""

    @property
    def model_name(self) -> str:
        return "fallback:test:one,test:two"


class _NamelessModel(TestModel):
    """A model that answers `''`, which core's own response wrapper can do."""

    @property
    def model_name(self) -> str:
        return ""
