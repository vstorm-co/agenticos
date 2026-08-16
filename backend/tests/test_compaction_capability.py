"""Tests for the compaction capability.

What is guarded: the configuration reaches the strategy it names, a summary the
strategy pays for is booked against the run that paid for it, and compaction
never leaves a tool return without the call it answers - which is what a resumed
approval replays through.
"""

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

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
from pydantic_ai.usage import RequestUsage, RunUsage
from pydantic_ai_harness.compaction import (
    ClearToolResults,
    SlidingWindowCompaction,
    SummarizingCompaction,
    TieredCompaction,
)

from app.agents.capabilities import CapabilityBinding, build, get
from app.agents.capabilities.budget import SpendLedger, metered_by
from app.agents.capabilities.compaction import (
    DEFAULT_SUMMARY_PROMPT,
    MODEL_CONTEXT_WINDOW_RESOURCE,
    CompactionConfig,
    ContextGauge,
    MeteredCompaction,
    NotifyingSummarizingCompaction,
    build_gauge,
    build_strategy,
)
from app.agents.compaction_events import CompactionEvent

pytestmark = pytest.mark.anyio


def _request_context(messages: list[ModelMessage], *, model: Any = None) -> ModelRequestContext:
    return ModelRequestContext(
        model=model if model is not None else TestModel(),
        messages=messages,
        model_settings=None,
        model_request_parameters=ModelRequestParameters(),
    )


def _response(*, input_tokens: int) -> ModelResponse:
    """A model response carrying what the provider said the request occupied."""
    return ModelResponse(
        parts=[TextPart(content="ok")], usage=RequestUsage(input_tokens=input_tokens)
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
    def test_the_default_strategy_keeps_what_the_old_turns_said(self):
        """The cheap strategies are cheap because they throw information away.

        A sliding window drops the oldest messages outright and clearing a tool
        result blanks an answer the agent may still need; an agent that silently
        forgets what it was told mid-run is a worse failure than a summary
        nobody asked for.
        """
        assert isinstance(build_strategy(CompactionConfig()), SummarizingCompaction)

    def test_compaction_is_deferred_until_the_window_is_nearly_full(self):
        """It is the point at which a run starts losing detail, so it waits."""
        assert CompactionConfig().max_fraction == 0.9

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
        assert [type(tier) for tier in tiered.tiers] == [
            ClearToolResults,
            NotifyingSummarizingCompaction,
        ]

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

    def test_the_profiles_recorded_window_is_used_when_nobody_overrode_it(self):
        """The provider's own number beats resolving one from the pricing snapshot.

        The snapshot records 1,000,000 for `anthropic:claude-sonnet-4-5` against
        a real 200,000, and answers nothing for the composite id a spec with
        fallbacks builds (#773).
        """
        tiered = build_strategy(CompactionConfig(strategy="tiered"), recorded_window=128_000)

        assert isinstance(tiered, TieredCompaction)
        assert tiered.context_window == 128_000
        assert [tier.context_window for tier in tiered.tiers] == [128_000, 128_000]

    def test_an_author_who_names_a_window_beats_the_recorded_one(self):
        """A provider publishes the maximum a model *can* be made to accept, and a
        beta- or tier-gated deployment gets less."""
        summary = build_strategy(
            CompactionConfig(strategy="summarize", context_window=32_000), recorded_window=1_000_000
        )

        assert isinstance(summary, SummarizingCompaction)
        assert summary.context_window == 32_000

    def test_a_profile_with_no_recorded_window_leaves_resolution_alone(self):
        """`None` has to reach the strategy as `None`, not as a number: that is
        what puts it back on resolving the window itself."""
        summary = build_strategy(CompactionConfig(strategy="summarize"), recorded_window=None)

        assert isinstance(summary, SummarizingCompaction)
        assert summary.context_window is None

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

    def test_the_run_hands_over_the_window_its_model_profile_recorded(self):
        """A capability must never reach for the model itself, which is what
        `resources` exists to prevent - so the factory puts the number there."""
        built = build(
            [CapabilityBinding(capability_id="compaction", config={"strategy": "summarize"})],
            resources={MODEL_CONTEXT_WINDOW_RESOURCE: 128_000},
        )

        assert built[0].wrapped.context_window == 128_000

    def test_a_resource_that_is_not_a_number_is_ignored_rather_than_passed_on(self):
        """`resources` is an untyped bag several subsystems write into, and a
        strategy handed a string for a token count fails inside a run."""
        built = build(
            [CapabilityBinding(capability_id="compaction")],
            resources={MODEL_CONTEXT_WINDOW_RESOURCE: "128k"},
        )

        assert built[0].wrapped.context_window is None


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


class TestSwitchingToASmallerModel:
    async def test_the_same_history_compacts_on_the_smaller_window(self):
        """The reason the trigger is a fraction resolved per request.

        The chat lets somebody switch model between turns, so a history that sat
        comfortably in a 1M-context window can be over the ceiling of a 128K one
        the moment they do - and the provider answers that by refusing the
        request, not by warning. Resolved per request, the very next turn
        compacts; fixed at build time, it would go on measuring against the model
        the agent was assembled with.
        """
        history = [_user("w " * 2_000) for _ in range(250)]

        def on(window: int) -> MeteredCompaction[None]:
            return MeteredCompaction(
                wrapped=build_strategy(
                    CompactionConfig(strategy="sliding_window", keep_messages=10),
                    recorded_window=window,
                )
            )

        roomy = await on(1_000_000).before_model_request(
            _run_context(), _request_context(list(history))
        )
        cramped = await on(128_000).before_model_request(
            _run_context(), _request_context(list(history))
        )

        assert len(roomy.messages) == len(history)
        assert len(cramped.messages) < len(history)

    async def test_an_agent_that_binds_nothing_is_only_told_how_bad_it_is(self):
        """The gauge reports; it never edits. An agent with no compaction bound
        reaches the ceiling and is refused, which is exactly why the reading is
        attached to every agent rather than only to the ones that compact."""
        gauge = ContextGauge()

        await build_gauge(gauge).after_model_request(
            _run_context(),
            request_context=_request_context([]),
            response=_response(input_tokens=250_000),
        )

        assert gauge.latest == 250_000


class TestAllowingForWhatEveryRequestCarries:
    """The trigger counts message parts; a request also carries the instructions
    and every tool schema, which the provider bills and no strategy can compact.

    Measured on a real agent here: 3,865 tokens charged against 60 the estimator
    saw. Left uncorrected, a gauge reading 77% of a window sat beside a trigger
    that had noticed nothing - the same ceiling described two ways, which is the
    defect this whole area kept producing.
    """

    @staticmethod
    def _fire(window: int, overhead: int | None, *, messages: int = 12) -> tuple[int, int]:
        """Run one request through the wrapper; answer (window used, messages kept)."""
        history = [_user("x" * 400) for _ in range(messages)]
        wrapped = build_strategy(
            CompactionConfig(
                strategy="sliding_window",
                max_fraction=0.5,
                keep_messages=2,
                context_window=window,
            )
        )
        capability = MeteredCompaction(wrapped=wrapped, gauge=ContextGauge(overhead=overhead))
        return capability, history

    async def test_a_measured_overhead_moves_the_trigger_down(self):
        capability, history = self._fire(10_000, 3_865)

        compacted = await capability.before_model_request(
            _run_context(), _request_context(list(history))
        )

        # 10,000 - 3,865/0.5 = 2,270: a trigger of 1,135 against ~1,200 of text.
        assert capability.wrapped.context_window == 2_270
        assert len(compacted.messages) < len(history)

    async def test_without_a_reading_the_trigger_is_left_alone(self):
        """Nothing is measured until a response has been seen, and guessing at the
        overhead would move the trigger by an invented number."""
        capability, history = self._fire(10_000, None)

        compacted = await capability.before_model_request(
            _run_context(), _request_context(list(history))
        )

        assert capability.wrapped.context_window == 10_000
        assert len(compacted.messages) == len(history)

    async def test_a_window_with_no_room_left_is_not_corrected(self):
        """When the overhead alone is past the trigger, no summary can get under
        it - the schemas are not in the history. A corrected window would ask for
        one on every request, for ever, paying each time."""
        capability, history = self._fire(5_000, 3_865)

        compacted = await capability.before_model_request(
            _run_context(), _request_context(list(history))
        )

        assert capability.wrapped.context_window == 5_000
        assert len(compacted.messages) == len(history)

    async def test_a_window_with_no_room_left_says_so(self):
        """Doing nothing is indistinguishable on screen from a setting that
        works, and this one cannot be made to work by waiting."""
        seen: list[CompactionEvent] = []

        async def sink(event: CompactionEvent) -> None:
            seen.append(event)

        capability, history = self._fire(5_000, 3_865)

        await capability.before_model_request(_ctx_with(sink), _request_context(list(history)))

        assert [event.kind for event in seen] == ["compaction_impossible"]
        assert (seen[0].overhead_tokens, seen[0].window_tokens) == (3_865, 5_000)

    async def test_it_says_so_once_rather_than_on_every_request(self):
        """A configuration, not an event: repeated on a hundred-step loop it would
        bury the turn's own steps under the same sentence."""
        seen: list[CompactionEvent] = []

        async def sink(event: CompactionEvent) -> None:
            seen.append(event)

        capability, history = self._fire(5_000, 3_865)

        for _ in range(3):
            await capability.before_model_request(_ctx_with(sink), _request_context(list(history)))

        assert len(seen) == 1

    async def test_a_window_that_works_says_nothing(self):
        seen: list[CompactionEvent] = []

        async def sink(event: CompactionEvent) -> None:
            seen.append(event)

        capability, history = self._fire(10_000, 3_865)

        await capability.before_model_request(_ctx_with(sink), _request_context(list(history)))

        assert seen == []

    async def test_the_correction_does_not_compound_over_a_tool_loop(self):
        """Applied to what the author configured, not to its own last answer -
        which would walk the trigger down to nothing over a long run."""
        capability, _history = self._fire(10_000, 1_000)

        for _ in range(3):
            await capability.before_model_request(_run_context(), _request_context([]))

        assert capability.wrapped.context_window == 8_000

    async def test_every_tier_of_a_tiered_strategy_is_corrected(self):
        """The orchestrator stops on its own target and each tier has its own; a
        tier left on the uncorrected number measures a different ceiling."""
        wrapped = build_strategy(
            CompactionConfig(strategy="tiered", max_fraction=0.5, context_window=10_000)
        )
        capability = MeteredCompaction(wrapped=wrapped, gauge=ContextGauge(overhead=1_000))

        await capability.before_model_request(_run_context(), _request_context([]))

        assert capability.wrapped.context_window == 8_000
        assert [tier.context_window for tier in capability.wrapped.tiers] == [8_000, 8_000]

    async def test_the_overhead_is_what_the_provider_charged_less_what_was_counted(self):
        gauge = ContextGauge()

        await build_gauge(gauge).after_model_request(
            _run_context(),
            request_context=_request_context([_user("x" * 400)]),
            response=_response(input_tokens=4_000),
        )

        # ~100 estimated tokens of message against 4,000 charged.
        assert gauge.overhead is not None
        assert 3_800 < gauge.overhead < 4_000


class TestTheSummaryPrompt:
    """What the summarising model is told, and why a binding may replace it."""

    def test_the_default_is_the_librarys_own_rather_than_a_copy(self):
        """A copy would go on being offered to authors long after the upstream one
        changed, and the difference between the prompt they edit and the prompt
        that runs would be invisible."""
        assert CompactionConfig().summary_prompt == DEFAULT_SUMMARY_PROMPT

    def test_an_edited_prompt_reaches_the_strategy(self):
        built = build_strategy(CompactionConfig(summary_prompt="Keep the numbers: {messages}"))

        assert isinstance(built, SummarizingCompaction)
        assert built.summary_prompt == "Keep the numbers: {messages}"

    def test_a_prompt_that_places_no_conversation_is_refused_at_publish(self):
        """The strategy formats this mid-turn, so the mistake would otherwise be a
        turn that summarised an empty conversation and threw the real one away -
        on exactly the long turns that compact."""
        with pytest.raises(ValidationError):
            CompactionConfig(summary_prompt="Summarise everything above.")


class TestSayingItIsWorking:
    """The frames a summary emits, and the two it deliberately does not.

    Compaction happens between a turn's model requests, where nothing streams. A
    summary is a whole request over a history that is by definition long, so the
    chat stopped dead for the length of it with nothing said - and waiting with no
    idea whether anything is happening is what makes somebody reload and lose the
    turn.
    """

    @staticmethod
    def _ctx(sink: object) -> RunContext[Any]:
        return RunContext(
            deps=SimpleNamespace(on_compaction=sink), model=TestModel(), usage=RunUsage()
        )

    async def test_it_says_it_started_and_what_it_came_to(self):
        seen: list[CompactionEvent] = []

        async def sink(event: CompactionEvent) -> None:
            seen.append(event)

        strategy = build_strategy(_triggers_immediately("summarize", keep_messages=2))
        history = [_user(f"turn {index}: " + "words " * 20) for index in range(20)]

        with patch.object(SummarizingCompaction, "compact", AsyncMock(return_value=history[:3])):
            await strategy.compact(history, self._ctx(sink))

        assert [event.kind for event in seen] == ["compaction_started", "compaction_finished"]
        assert seen[0].messages_before == 20
        assert (seen[1].messages_before, seen[1].messages_after) == (20, 3)

    async def test_a_summary_that_raised_still_closes_the_frame(self):
        """Otherwise a surface spins for ever, and the run carries on either way."""
        seen: list[CompactionEvent] = []

        async def sink(event: CompactionEvent) -> None:
            seen.append(event)

        strategy = build_strategy(_triggers_immediately("summarize"))

        with (
            patch.object(SummarizingCompaction, "compact", AsyncMock(side_effect=RuntimeError)),
            pytest.raises(RuntimeError),
        ):
            await strategy.compact([_user("x")], self._ctx(sink))

        assert [event.kind for event in seen] == ["compaction_started", "compaction_finished"]
        # Not a number: the history is whatever it was, and one here would report
        # a compaction that did not happen.
        assert seen[1].messages_after is None

    async def test_a_surface_that_cannot_narrate_gets_a_silent_summary(self):
        """A progress report, not a permission: the summary still happens."""
        strategy = build_strategy(_triggers_immediately("summarize", keep_messages=2))
        history = [_user("x") for _ in range(5)]

        with patch.object(
            SummarizingCompaction, "compact", AsyncMock(return_value=history[:2])
        ) as summarised:
            compacted = await strategy.compact(history, self._ctx(None))

        assert summarised.await_count == 1
        assert len(compacted) == 2

    def test_the_strategies_that_return_at_once_say_nothing(self):
        """A frame for them would be a spinner that appears and vanishes within a
        frame. Only the one that makes a model request is narrated."""
        for name in ("clear_tool_results", "sliding_window"):
            built = build_strategy(CompactionConfig(strategy=name))
            assert not isinstance(built, NotifyingSummarizingCompaction)

    def test_the_summarising_tier_of_tiered_is_narrated_too(self):
        """`TieredCompaction` drives its tiers through the same `compact`, so the
        hook covers the escalating strategy without a second implementation."""
        tiered = build_strategy(CompactionConfig(strategy="tiered"))

        assert isinstance(tiered, TieredCompaction)
        assert isinstance(tiered.tiers[-1], NotifyingSummarizingCompaction)


class TestTheGauge:
    """What the context gauge reports, and where the number comes from.

    Attached to every agent rather than to one that compacts, because the warning
    matters most to the agent that will *not*: that is the one that reaches the
    ceiling and is refused by the provider (#774).
    """

    async def test_it_reports_what_the_provider_says_the_request_carried(self):
        """Measured, not estimated.

        Counting the message parts is the obvious way and it is short by the tool
        schemas, which are billed on every request: a real conversation here
        measured 1,688 by the estimate against 5,007 the provider charged for.
        Three times short is not a rounding error at 90% of a window.
        """
        gauge = ContextGauge()
        capability = build_gauge(gauge)

        await capability.after_model_request(
            _run_context(),
            request_context=_request_context([]),
            response=_response(input_tokens=5_007),
        )

        assert gauge.latest == 5_007

    async def test_the_newest_reading_wins_because_a_tool_loop_grows(self):
        """Every step adds to the history, so the last request is the peak."""
        gauge = ContextGauge()
        capability = build_gauge(gauge)

        for size in (900, 4_100, 12_600):
            await capability.after_model_request(
                _run_context(),
                request_context=_request_context([]),
                response=_response(input_tokens=size),
            )

        assert gauge.latest == 12_600

    async def test_a_response_that_reported_nothing_leaves_the_last_reading_alone(self):
        """Blanking it would report an empty context for a run that had one."""
        gauge = ContextGauge()
        capability = build_gauge(gauge)

        await capability.after_model_request(
            _run_context(),
            request_context=_request_context([]),
            response=_response(input_tokens=4_100),
        )
        await capability.after_model_request(
            _run_context(),
            request_context=_request_context([]),
            response=_response(input_tokens=0),
        )

        assert gauge.latest == 4_100

    async def test_it_observes_and_never_edits(self):
        """A gauge that rewrote a response would be a compaction nobody asked for."""
        gauge = ContextGauge()
        answered = _response(input_tokens=10)

        returned = await build_gauge(gauge).after_model_request(
            _run_context(), request_context=_request_context([]), response=answered
        )

        assert returned is answered

    def test_a_run_that_made_no_request_leaves_it_empty(self):
        """Refused before it started, or stopped by a budget on the first check."""
        assert ContextGauge().latest is None


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


def _ctx_with(sink: object) -> RunContext[Any]:
    """A run whose surface can be told things - the chat, in practice."""
    return RunContext(deps=SimpleNamespace(on_compaction=sink), model=TestModel(), usage=RunUsage())


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
